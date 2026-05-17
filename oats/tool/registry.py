"""
Tool registry and base definitions for the OATS agent framework.

This module provides the core abstractions for tool registration and execution:

- :class:`Tool` — Abstract base class that all tools inherit from.
- :class:`ToolContext` — Context object passed to every tool execution.
- :class:`ToolResult` — Result object returned by tools after execution.
- :class:`ToolRegistry` — Central registry for discovering and managing tools.

Module-level convenience functions:

- :func:`get_tool_registry` — Get the singleton registry instance.
- :func:`register_tool` — Register a tool in the global registry.
- :func:`get_tool` — Look up a tool by name or alias.
- :func:`list_tools` — List all registered tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
from typing import Union
from pydantic import BaseModel
from oats.log import cl

log = cl('tool.registry')


class ToolContext(BaseModel):
    """Context passed to every tool execution.

    Carries session identity, directory paths, and optional state
    (file cache, agent nesting info) that tools may need.

    Attributes:
        session_id: Unique identifier for the current session.
        project_dir: Root directory of the project.
        working_dir: Current working directory for the tool.
        user_confirmed: Whether the user has confirmed this action.
        parent_session_id: ID of the parent session (for sub-agents).
        agent_depth: Current nesting depth of sub-agents.
        max_agent_depth: Maximum allowed sub-agent nesting depth.
        file_cache: Optional file state cache set by the session processor.
    """

    session_id: str
    project_dir: Path
    working_dir: Path
    user_confirmed: bool = False

    # Sub-agent support
    parent_session_id: Optional[str] = None
    agent_depth: int = 0
    max_agent_depth: int = 3

    # File state cache (optional, set by SessionProcessor)
    file_cache: Optional[Any] = None

    class Config:
        """Pydantic config to allow arbitrary types (e.g. ``Path``)."""

        arbitrary_types_allowed = True


@dataclass
class ToolResult:
    """Result returned by a tool after execution.

    Attributes:
        title: Short title for the result (shown in the UI).
        output: The main output text.
        metadata: Arbitrary key-value pairs for additional context.
        error: Error message if the tool failed.
        attachments: List of attachment dicts (files, images, etc.).
    """

    title: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)


class Tool(ABC):
    """Abstract base class for all tools.

    Each tool must implement :meth:`name`, :meth:`description`,
    :meth:`parameters`, and :meth:`execute`. Optional hooks include
    :meth:`requires_permission`, :meth:`is_concurrency_safe`, and
    :meth:`to_definition`.

    Subclasses represent individual capabilities (read, write, edit, bash, etc.)
    that the agent can invoke during a session.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for the tool parameters."""
        pass

    @abstractmethod
    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute the tool with the given arguments."""
        pass

    def is_concurrency_safe(self, args: dict[str, Any] | None = None) -> bool:
        """
        Whether this tool can safely run concurrently with other tools.

        Read-only tools (read, glob, grep) are safe. Write tools (write, edit,
        bash) are not, because they can have side effects that conflict.

        Override in subclasses to return True for read-only tools.
        """
        return False

    @property
    def aliases(self) -> list[str]:
        """Optional alternate names for backwards compatibility."""
        return []

    @property
    def keywords(self) -> list[str]:
        """Short search terms describing when this tool should be used."""
        return []

    @property
    def always_load(self) -> bool:
        """
        Whether this tool should almost always be available to the model.

        Mirrors Claude Code's "alwaysLoad" concept in a lightweight way so
        essential tools stay visible even when we rank the broader tool set.
        """
        return False

    @property
    def strict(self) -> bool:
        """
        Whether provider-side tool schema adherence should be as strict as
        the serving stack supports.
        """
        return False

    def requires_permission(self, args: dict[str, Any], ctx: ToolContext) -> str | None:
        """
        Check if this execution requires user permission.

        Returns None if no permission needed, or a description of what permission is needed.
        """
        return None

    def to_definition(self) -> dict[str, Any]:
        """Convert this tool to an LLM-compatible tool definition.

        Returns:
            A dict with ``name``, ``description``, and ``parameters`` keys
            suitable for inclusion in an LLM function-calling schema.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """Central registry for all available tools.

    Maintains a name→tool mapping and supports lookup by name or alias.
    Use the module-level convenience functions (:func:`register_tool`,
    :func:`get_tool`, :func:`list_tools`) to interact with the global instance.
    """

    def __init__(self) -> None:
        """Initialize an empty tool registry."""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool under its primary name.

        Args:
            tool: The :class:`Tool` instance to register.
        """
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by its primary name or any of its aliases.

        Args:
            name: The tool name or alias to look up.

        Returns:
            The :class:`Tool` instance, or ``None`` if not found.
        """
        tool = self._tools.get(name)
        if tool is not None:
            return tool
        for candidate in self._tools.values():
            if name in candidate.aliases:
                return candidate
        return None

    def list(self) -> list[Tool]:
        """List all registered tools.

        Returns:
            A list of all :class:`Tool` instances.
        """
        return list(self._tools.values())

    def to_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in LLM-compatible format.

        Returns:
            A list of dicts with ``name``, ``description``, and ``parameters``.
        """
        return [tool.to_definition() for tool in self._tools.values()]


# Global tool registry
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry, creating it if necessary.

    Returns:
        The singleton :class:`ToolRegistry` instance.
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def register_tool(tool: Tool) -> None:
    """Register a tool in the global registry.

    Args:
        tool: A :class:`Tool` instance to register.
    """
    get_tool_registry().register(tool)


def get_tool(name: str) -> Tool | None:
    """Get a tool by name or alias from the global registry.

    Args:
        name: The tool name or alias to look up.

    Returns:
        The :class:`Tool` instance, or ``None`` if not found.
    """
    return get_tool_registry().get(name)


def list_tools() -> list[Tool]:
    """List all registered tools.

    Returns:
        A list of all :class:`Tool` instances in the global registry.
    """
    return get_tool_registry().list()
