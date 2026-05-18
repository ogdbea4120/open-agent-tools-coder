#!/usr/bin/env python3

"""
ff -m 'get utc' -n -p vllm-small -z hosted_vllm/MODEL_NAME
"""

from typing import Optional
from pydantic import BaseModel
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
        core_impls: dict mapping core tool names to implementations.
        mcp_tools: MCP (Model Context Protocol) tools selected.
        mcp_tool_names: Set of MCP tool names.
        mcp_impls: dict mapping MCP tool names to implementations.
        local_tools: Local/external tools selected.
        local_tool_names: Set of local tool names.
        local_impls: dict mapping local tool names to implementations.
        all_tools: Union of all selected tools.
        all_tool_names: Set of all selected tool names.
        plan_tools: Tools relevant to planning mode.
        plan_tool_names: Set of plan tool names.
        agent_tools: Tools relevant to agent mode.
        agent_tool_names: Set of agent tool names.
        best_tools: Best-match tools from BM25 scoring.
        best_tool_names: Set of best-match tool names.
        best_files: Files associated with best-match tools.
        best_impls: dict mapping best tool names to implementations.
        all_tools_dict: dict of all tools by name.
        provider_tool_map: Mapping of providers to their tools.
    """

    prompt: str = None
    found_best_tool: bool = False
    found_all_tools: list = []
    core_tools: list[Tool] = []
    core_tool_names: set[str] = set()
    core_impls: dict = {}
    mcp_tools: list[Tool] = []
    mcp_tool_names: set[str] = set()
    mcp_impls: dict = {}
    local_tools: list[LocalTool] = []
    local_tool_names: set[str] = set()
    local_impls: dict = {}
    all_tools: list[Tool] = []
    all_tool_names: set[str] = set()
    plan_tools: list[Tool] = []
    plan_tool_names: set[str] = set()
    agent_tools: list[Tool] = []
    agent_tool_names: set[str] = set()
    best_tools: dict = {}
    best_tool_names: set[str] = set()
    best_files: list = []
    best_impls: dict = {}
    all_tools_dict: dict = {}
    provider_tool_map: dict = {}

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        # Allow extra fields if needed
        extra='allow'
    )
