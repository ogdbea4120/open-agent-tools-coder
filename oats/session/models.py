#!/usr/bin/env python3

"""
Coder Session Models
"""

from typing import Dict, Optional, Any
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict
from oats.tool.registry import Tool
from oats.call_tool_with_loader1 import LocalTool

class SelectedToolsManifest(BaseModel):
    """Manifest of tools selected for a given user prompt.

    Holds categorized tool lists (core, MCP, local, plan, agent) along with
    their names and implementations. Used by the session processor to build
    the tool definitions sent to the LLM for each turn.

    Attributes:
        prompt: The user prompt that triggered tool selection.
        found_best_tool: Whether a best-match tool was found.
        found_all_tools: List of all discovered tools.
        core_tools: Core built-in tools selected for this prompt.
        core_tool_names: Set of core tool names.
        core_impls: Dict mapping core tool names to implementations.
        mcp_tools: MCP (Model Context Protocol) tools selected.
        mcp_tool_names: Set of MCP tool names.
        mcp_impls: Dict mapping MCP tool names to implementations.
        local_tools: Local/external tools selected.
        local_tool_names: Set of local tool names.
        local_impls: Dict mapping local tool names to implementations.
        all_tools: Union of all selected tools.
        all_tool_names: Set of all selected tool names.
        plan_tools: Tools relevant to planning mode.
        plan_tool_names: Set of plan tool names.
        agent_tools: Tools relevant to agent mode.
        agent_tool_names: Set of agent tool names.
        best_tools: Best-match tools from BM25 scoring.
        best_tool_names: Set of best-match tool names.
        best_files: Files associated with best-match tools.
        best_impls: Dict mapping best tool names to implementations.
        all_tools_dict: Dict of all tools by name.
        provider_tool_map: Mapping of providers to their tools.
    """
    prompt: str | None = None
    found_best_tool: bool = False
    found_all_tools: list = Field(default_factory=list)
    core_tools: list[Tool] = Field(default_factory=list)
    core_tool_names: set[str] = Field(default_factory=set)
    core_impls: dict[str, Any] = Field(default_factory=dict)
    mcp_tools: list[Tool] = Field(default_factory=list)
    mcp_tool_names: set[str] = Field(default_factory=set)
    mcp_impls: dict[str, Any] = Field(default_factory=dict)
    local_tools: list[LocalTool] = Field(default_factory=list)
    local_tool_names: set[str] = Field(default_factory=set)
    local_impls: dict[str, Any] = Field(default_factory=dict)
    all_tools: list[Tool] = Field(default_factory=list)
    all_tool_names: set[str] = Field(default_factory=set)
    plan_tools: list[Tool] = Field(default_factory=list)
    plan_tool_names: set[str] = Field(default_factory=set)
    agent_tools: list[Tool] = Field(default_factory=list)
    agent_tool_names: set[str] = Field(default_factory=set)
    best_tools: dict[str, Any] = Field(default_factory=dict)
    best_tool_names: set[str] = Field(default_factory=set)
    best_files: list[Any] = Field(default_factory=list)
    best_impls: dict[str, Any] = Field(default_factory=dict)
    all_tools_dict: dict[str, Any] = Field(default_factory=dict)
    provider_tool_map: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="allow",
    )
