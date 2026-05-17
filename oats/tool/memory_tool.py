"""
Memory tools — read, write, and delete persistent memories.

Provides three tools for managing persistent memories that survive across
sessions:

- :class:`MemoryReadTool` — List or search persistent memories.
- :class:`MemoryWriteTool` — Create or update a persistent memory.
- :class:`MemoryDeleteTool` — Delete a persistent memory by ID.

Helper functions:

- :func:`_get_manager` — Create a :class:`MemoryManager` from the tool context.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.memory.models import Memory, MemoryType
from oats.memory.manager import MemoryManager
from oats.log import cl

log = cl("tool.memory")


def _get_manager(ctx: ToolContext) -> MemoryManager:
    """Create a MemoryManager from the tool context.

    Args:
        ctx: The tool execution context.

    Returns:
        A :class:`MemoryManager` scoped to the project directory.
    """
    return MemoryManager(project_dir=ctx.project_dir)


class MemoryReadTool(Tool):
    """List or search persistent memories across sessions.

    Memories contain user preferences, project context, feedback, and
    references. Supports keyword search and type filtering.

    Example:
        ::

            memory_read
            memory_read query="authentication"
            memory_read type_filter="project"
    """

    @property
    def name(self) -> str:
        return "memory_read"

    @property
    def description(self) -> str:
        return (
            "List or search persistent memories. Memories persist across sessions "
            "and contain user preferences, project context, feedback, and references. "
            "Use without a query to list all, or provide a query to search."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional search query to filter memories by keyword.",
                },
                "type_filter": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": "Optional filter by memory type.",
                },
            },
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """List or search persistent memories.

        If a query is provided, searches memories by keyword. Otherwise, loads
        all memories. An optional type filter can narrow results.

        Args:
            args: May contain ``query`` (str) and ``type_filter`` (str).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the matching memories.
        """
        manager = _get_manager(ctx)
        query = args.get("query")
        type_filter = args.get("type_filter")

        if query:
            memories = await manager.search(query)
        else:
            memories = await manager.load_all()

        # Apply type filter
        if type_filter:
            try:
                mem_type = MemoryType(type_filter)
                memories = [m for m in memories if m.type == mem_type]
            except ValueError:
                pass

        if not memories:
            return ToolResult(
                title="Memories",
                output="No memories found.",
                metadata={"count": 0},
            )

        lines = []
        for mem in memories:
            tags = f" [{', '.join(mem.tags)}]" if mem.tags else ""
            lines.append(
                f"- **{mem.title}** ({mem.type.value}){tags}\n"
                f"  ID: {mem.id[:8]}\n"
                f"  {mem.content[:200]}{'...' if len(mem.content) > 200 else ''}"
            )

        return ToolResult(
            title=f"Memories ({len(memories)})",
            output="\n\n".join(lines),
            metadata={"count": len(memories)},
        )


class MemoryWriteTool(Tool):
    """Create or update a persistent memory for future sessions.

    Supports four memory types: ``user`` (preferences/role), ``feedback``
    (how to approach work), ``project`` (ongoing goals/decisions), and
    ``reference`` (external resources). Scope can be ``project`` (local to
    repo) or ``user`` (global).

    Example:
        ::

            memory_write title="Preferred style" content="Use PEP 8" type="user"
    """

    @property
    def name(self) -> str:
        return "memory_write"

    @property
    def description(self) -> str:
        return (
            "Save a persistent memory that will be available in future sessions. "
            "Types: 'user' (preferences/role), 'feedback' (how to approach work), "
            "'project' (ongoing goals/decisions), 'reference' (external resources). "
            "Scope: 'project' (local to repo) or 'user' (global)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short descriptive title for the memory.",
                },
                "content": {
                    "type": "string",
                    "description": "The memory content. For feedback/project types, include Why and How to apply.",
                },
                "type": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": "Memory type. Default: 'project'.",
                    "default": "project",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for categorization.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "user"],
                    "description": "Where to store: 'project' (repo-local) or 'user' (global). Default: 'project'.",
                    "default": "project",
                },
            },
            "required": ["title", "content"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Save a new persistent memory.

        Args:
            args: Must contain ``title`` (str) and ``content`` (str). May contain
                ``type`` (str), ``tags`` (list of str), and ``scope`` (str).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` confirming the memory was saved with its ID.
        """
        manager = _get_manager(ctx)

        title = args.get("title", "")
        content = args.get("content", "")
        mem_type_str = args.get("type", "project")
        tags = args.get("tags", [])
        scope = args.get("scope", "project")

        if not title or not content:
            return ToolResult(
                title="Memory Error",
                output="",
                error="Both title and content are required.",
            )

        try:
            mem_type = MemoryType(mem_type_str)
        except ValueError:
            mem_type = MemoryType.PROJECT

        memory = Memory(
            type=mem_type,
            title=title,
            content=content,
            tags=tags,
            source="agent",
        )

        saved = await manager.save(memory, scope=scope)

        return ToolResult(
            title="Memory Saved",
            output=f"Memory '{saved.title}' saved (type={saved.type.value}, scope={scope}, id={saved.id[:8]}).",
            metadata={"memory_id": saved.id, "scope": scope},
        )


class MemoryDeleteTool(Tool):
    """Delete a persistent memory by its ID (partial match accepted).

    Searches all memories for an ID that starts with the given prefix
    and deletes the first match.

    Example:
        ::

            memory_delete memory_id="abc12345"
    """

    @property
    def name(self) -> str:
        return "memory_delete"

    @property
    def description(self) -> str:
        return "Delete a persistent memory by its ID. Use memory_read to find IDs."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "The memory ID to delete (first 8 chars is enough).",
                },
            },
            "required": ["memory_id"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Delete a persistent memory by its ID (partial match accepted).

        Args:
            args: Must contain ``memory_id`` (str — first 8 chars is enough).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` confirming deletion or an error.
        """
        manager = _get_manager(ctx)
        memory_id = args.get("memory_id", "")

        if not memory_id:
            return ToolResult(
                title="Memory Error",
                output="",
                error="memory_id is required.",
            )

        # Search for partial ID match
        all_memories = await manager.load_all()
        matching = [m for m in all_memories if m.id.startswith(memory_id)]

        if not matching:
            return ToolResult(
                title="Memory Not Found",
                output="",
                error=f"No memory found with ID starting with '{memory_id}'.",
            )

        deleted = await manager.delete(matching[0].id)
        if deleted:
            return ToolResult(
                title="Memory Deleted",
                output=f"Memory '{matching[0].title}' deleted.",
                metadata={"memory_id": matching[0].id},
            )
        else:
            return ToolResult(
                title="Memory Error",
                output="",
                error="Failed to delete memory.",
            )
