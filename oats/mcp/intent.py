"""
Intent-aware tool selector for the session processor.

This module bridges user prompts with the MCP tool calling protocol.
Instead of sending ALL 32+ tools to the LLM on every request, it:

1. Queries the BM25 index first — if there's a strong MCP match, that IS the intent
2. Falls back to keyword detection for explicit MCP signals
3. When MCP intent detected: includes MCP meta-tools + standard tools
   (so the LLM can compare and pick the best approach)
4. Enriches the system prompt with the pre-classified MCP resource

The index is built at startup from OpenAPI specs. At runtime, the user's
message is classified against the index to find the best MCP resource,
and the system prompt is enriched with the exact tool name and endpoint.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Tuple
from oats.tool.registry import Tool, list_tools, get_tool, register_tool
from oats.call_tool_with_loader1 import load_tools_from_repo_uses_index
from oats.call_tool_with_loader1 import LocalTool
from oats.mcp.ranking import ToolRanker
from oats.mcp.models import MCPToolDefinition
from oats.session.models import SelectedToolsManifest
from oats.log import gl

log = gl("mcp.intent")

# Core tools that are ALWAYS included (the agent needs these to function)
ALWAYS_INCLUDE = {
    "read", "write", "edit", "bash", "glob", "grep",
    "todowrite", "todoread", "question",
    "memory_read", "memory_write",
}

# MCP meta-tools: included when external tool calling is detected
MCP_META_TOOLS = {
    "mcp_discover", "mcp_call", "mcp_chain", "mcp_fan_out",
    "mcp_rank", "mcp_session", "mcp_server_manage",
}

# Explicit keywords that always signal MCP intent (even without index)
MCP_EXPLICIT_SIGNALS = [
    "mcp", "tool call", "tool calling", "litellm",
    "discover tools", "find tools", "available tools",
    "fan out", "fan-out", "mcp_call", "mcp_discover",
]

# BM25 score threshold: if the index returns a match above this,
# treat it as MCP intent even without keyword signals
INDEX_INTENT_THRESHOLD = 0.5

# Patterns that suggest planning/multi-step work
PLANNING_SIGNALS = [
    "plan", "step by step", "multi-step", "workflow",
    "first.*then", "sequence", "pipeline",
]

# Agent delegation signals
AGENT_SIGNALS = [
    "sub-agent", "subagent", "delegate", "in parallel",
    "explore separately", "background", "spawn agent",
    "agent", "launch.*agent", "use.*agent",
]

# Agent tools
AGENT_TOOLS = {"agent", "agent_status"}

def get_coder_tool_index() -> str:
    """Return the path to the coder tool uses index from the environment."""
    coder_tools_index = os.getenv("CODER_TOOL_USES_INDEX", "./.ai/AGENT.repo_uses.python.tools.json")
    return coder_tools_index

CODER_TOOLS_INDEX = get_coder_tool_index()

def select_tools_for_prompt(
    prompt: str,
    all_tools: list[Tool] | None = None,
    mcp_tools: list[MCPToolDefinition] | None = None,
    needs_local_tools: bool = False,
    ranker: ToolRanker | None = None,
    max_tools: int = 30,
    project_dir: str = None,
    verbose: bool = False,
) -> SelectedToolsManifest:
    """Select the most relevant tools for a user prompt.

    Strategy:

    1. Always include core tools (read, write, edit, bash, etc.)
    2. Check the BM25 index — if there's a match above threshold,
       the user wants an MCP resource (even if they didn't say "mcp")
    3. Fall back to explicit keyword detection
    4. When MCP detected: include MCP meta-tools AND standard tools
       (let the LLM decide the best approach)
    5. When NOT MCP: include standard extras only
    """
    stm = SelectedToolsManifest()
    if all_tools is None:
        all_tools = list_tools()

    prompt_lower = prompt.lower()

    # 1. Always include core tools
    for tool in all_tools:
        if tool.name in ALWAYS_INCLUDE or tool.always_load:
            stm.core_tools.append(tool)
            stm.core_tool_names.add(tool.name)
            stm.all_tools.append(tool)
            stm.all_tool_names.add(tool.name)

    found_best_tool = False
    local_tool_impls = []
    local_tool_names = []
    local_tools: list[LocalTool] = []

    best_local_tools: list = [LocalTool]
    best_local_tool_names: list = []

    all_local_tools = []
    all_tool_impls = {}
    best_files = []
    best_tools = []
    best_impls = {}
    # 2. Determine "best" 30 local source tools
    if needs_local_tools:
        max_tools = 30
        found_best_tool, found_all_tools, all_tool_impls, best_files, best_tools, best_impls, best_local_tools, best_local_tool_names = load_tools_from_repo_uses_index(prompt=prompt)
        stm.best_tools = best_tools
        stm.best_impls = best_impls
        stm.best_tool_names = best_local_tool_names
        stm.local_impls = best_impls
        if found_best_tool:
            for tool in best_local_tools[:max_tools]:
                tool_name = tool.name
                if tool_name is not None:
                    if tool_name not in stm.all_tools_dict:
                        stm.local_tools.append(tool)
                        stm.local_tool_names.add(tool.name)
                        stm.all_tools.append(tool)
                        stm.all_tool_names.add(tool.name)
                        stm.all_tools_dict[tool.name] = tool
                        if verbose:
                            log.debug(f'Semantic Match - LocalTool(name={tool.name}, params: {tool.parameters})')
                        register_tool(tool)
        if len(stm.local_tools) == 0:
            for tool in found_all_tools:
                tool_name = tool.name
                if tool_name is not None:
                    if tool_name.lower() in prompt[0:200].lower():
                        stm.local_tools.append(tool)
                        stm.local_tool_names.add(tool.name)
                        stm.all_tools.append(tool)
                        stm.all_tool_names.add(tool.name)
                        stm.all_tools_dict[tool.name] = tool
                        if verbose:
                            log.debug(f'Prompt Match - LocalTool(name={tool.name}, params: {tool.parameters})')
                        register_tool(tool)

    # 3. Detect MCP intent — index first, then keywords
    needs_mcp, index_match = _detect_mcp_intent(prompt_lower, Path(project_dir))

    if needs_mcp:
        # Include MCP meta-tools
        for tool in all_tools:
            if tool.name in MCP_META_TOOLS and tool.name not in stm.all_tools_dict:
                if verbose:
                    log.debug(f'MCPTool(name={tool.name}, params:\n```\n{tool.parameters}\n```\n')
                stm.mcp_tools.append(tool)
                stm.mcp_tool_names.add(tool.name)
                stm.all_tools.append(tool)
                stm.all_tool_names.add(tool.name)
                stm.all_tools_dict[tool.name] = tool
        # ALSO include standard web tools so the LLM can compare approaches
        standard_extras = {"webfetch", "websearch", "multiedit", "patch"}
        for tool in all_tools:
            if tool.name in standard_extras and tool.name not in stm.all_tools_dict:
                stm.core_tools.append(tool)
                stm.core_tool_names.add(tool.name)
                stm.all_tools.append(tool)
                stm.all_tool_names.add(tool.name)
                stm.all_tools_dict[tool.name] = tool

        if index_match:
            if verbose:
                log.info(
                    f"mcp_intent_from_index: {index_match.get('name', '?')} "
                    f"(score={index_match.get('score', 0):.3f})"
                )
    else:
        # Standard tools only
        standard_extras = {"webfetch", "websearch", "multiedit", "patch"}
        for tool in all_tools:
            if tool.name in standard_extras and tool.name not in stm.all_tools_dict:
                stm.core_tools.append(tool)
                stm.core_tool_names.add(tool.name)
                stm.all_tools.append(tool)
                stm.all_tool_names.add(tool.name)
                stm.all_tools_dict[tool.name] = tool

    # 4. Detect if planning tools are needed
    if _detect_planning_intent(prompt_lower):
        for tool in all_tools:
            if tool.name in ("plan_enter", "plan_exit", "plan_status"):
                if tool.name not in stm.all_tools_dict:
                    stm.plan_tools.append(tool)
                    stm.plan_tool_names.add(tool.name)
                    stm.all_tools.append(tool)
                    stm.all_tool_names.add(tool.name)
                    stm.all_tools_dict[tool.name] = tool

    # 5. Detect if agent/delegation tools are needed
    if _detect_agent_intent(prompt_lower):
        for tool in all_tools:
            if tool.name in AGENT_TOOLS and tool.name not in stm.all_tools_dict:
                stm.agent_tools.append(tool)
                stm.agent_tool_names.add(tool.name)
                stm.all_tools.append(tool)
                stm.all_tool_names.add(tool.name)
                stm.all_tools_dict[tool.name] = tool

    # 6. Fill remaining slots with other relevant tools (NOT MCP meta-tools unless needed)
    remaining_slots = max_tools - len(stm.all_tool_names)
    if remaining_slots > 0:
        unselected = [
            t for t in all_tools
            if t.name not in stm.all_tools_dict
            and (needs_mcp or t.name not in MCP_META_TOOLS)
        ]
        scored = []
        for tool in unselected:
            score = _keyword_relevance(prompt_lower, tool)
            if score > 0:
                scored.append((score, tool))
        scored.sort(key=lambda x: x[0], reverse=True)
        for _, tool in scored[:remaining_slots]:
            stm.all_tools.append(tool)
            stm.all_tool_names.add(tool.name)
            stm.all_tools_dict[tool.name] = tool

    # 7. Defensive Tool Calling check with verbose logging
    if len(stm.all_tool_names) == 0:
        for tool in all_tools:
            if tool.name in ALWAYS_INCLUDE or tool.always_load:
                stm.all_tools.append(tool)
                stm.all_tool_names.add(tool.name)
                stm.all_tools_dict[tool.name] = tool
    if len(stm.all_tool_names) == 0:
        log.error(
            f"ERROR_CONFIRM_init_tools_ran_hit_no_default_tools_found fallback_tools: {len(stm.all_tool_names)}/{len(all_tools)} tools "
            f"(mcp={'yes' if needs_mcp else 'no'}) "
            f"for prompt: {prompt[:80]}..."
        )
    if verbose:
        log.info(
            f"tool_selection: {len(stm.all_tool_names)}/{len(all_tools)} tools "
            f"(mcp={'yes' if needs_mcp else 'no'}) "
            f"for prompt: {prompt[:80]}..."
        )
    return stm


def build_mcp_system_context(
    prompt: str,
    mcp_tools: list[MCPToolDefinition] | None = None,
    project_dir: Any = None,
) -> str:
    """
    Build compact MCP context for the system prompt.

    Only includes the best-match resource and a brief tool list.
    Usage instructions are omitted — tool schemas already describe arguments.
    """
    lines: list[str] = []

    # --- Index-based auto-routing ---
    recommended = _classify_from_index(prompt, project_dir)
    if recommended:
        call_sig = f"{recommended['server_name']}.{recommended['name']}"
        desc = recommended.get('description', '')[:150]
        lines.append(f"\n# MCP: use `mcp_call(tool_name=\"{call_sig}\", arguments={{...}})` — {desc}")

        alternatives = _search_index(prompt, project_dir, top_k=3)
        if len(alternatives) > 1:
            alt_names = [f"`{a['server_name']}.{a['name']}`" for _, a in alternatives[1:3]]
            lines.append(f"Alternatives: {', '.join(alt_names)}")

    # --- Discovered tools list (compact) ---
    if mcp_tools:
        lines.append("\n# MCP Tools (use `mcp_call` to invoke, `mcp_discover` to refresh)")
        for tool in mcp_tools[:10]:
            lines.append(f"- `{tool.name}`: {tool.description[:80]}")

    # --- No match at all ---
    if not recommended and not mcp_tools:
        lines.append("\n# MCP: servers configured but not indexed. Use `mcp_discover` first.")

    return "\n".join(lines)


def enrich_mcp_tool_description(tool: MCPToolDefinition) -> str:
    """Enrich an MCP tool's description with routing info."""
    parts = [tool.description[:300]]
    if tool.mcp_function_name:
        parts.append(f"[MCP function: {tool.mcp_function_name}]")
    if tool.call_endpoint:
        parts.append(f"[Endpoint: {tool.call_endpoint}]")
    if tool.tags:
        parts.append(f"[Tags: {', '.join(tool.tags[:5])}]")
    return " ".join(parts)


# --- Private helpers ---

def _detect_mcp_intent(
    prompt_lower: str,
    project_dir: Any = None,
) -> tuple[bool, dict[str, Any] | None]:
    """
    Detect if the prompt needs MCP / external tools.

    Returns (needs_mcp, index_match_or_none).

    Strategy:
    1. Check the BM25 index first — if there's a strong match, that's MCP intent.
       This catches "search business wire" even without the keyword "mcp".
    2. Fall back to explicit keyword signals for cases like "use mcp" or "litellm".
    """
    # Strategy 1: Ask the index
    index_match = _classify_from_index(prompt_lower, project_dir)
    if index_match and index_match.get("score", 0) >= INDEX_INTENT_THRESHOLD:
        return True, index_match

    # Strategy 2: Explicit keyword signals
    for signal in MCP_EXPLICIT_SIGNALS:
        if signal in prompt_lower:
            return True, None

    return False, None


def _detect_agent_intent(prompt_lower: str) -> bool:
    """Detect if the prompt wants to delegate work to sub-agents."""
    for signal in AGENT_SIGNALS:
        if re.search(signal, prompt_lower):
            return True
    return False


def _detect_planning_intent(prompt_lower: str) -> bool:
    """Check if the prompt signals planning or multi-step work."""
    for signal in PLANNING_SIGNALS:
        if re.search(signal, prompt_lower):
            return True
    return False


def _tool_terms(tool: Tool) -> list[str]:
    """Extract searchable terms from a tool (name, description, aliases, keywords)."""
    terms = [tool.name, tool.description.lower()]
    terms.extend(alias.lower() for alias in tool.aliases)
    terms.extend(keyword.lower() for keyword in tool.keywords)
    return [t for t in terms if t]


def _keyword_relevance(prompt_lower: str, tool: Tool) -> float:
    """
    Lightweight ranking inspired by Claude Code's tool metadata.

    We combine exact phrase matches from tool aliases/keywords with softer
    description matches so optional tools surface more reliably without
    forcing the whole tool catalog into every prompt.
    """
    score = 0.0
    terms = _tool_terms(tool)
    prompt_tokens = set(re.findall(r"[a-z0-9_./-]+", prompt_lower))

    for term in terms:
        if term in prompt_lower:
            score += 3.0 if term in tool.keywords or term in tool.aliases else 1.5
            continue
        term_tokens = set(re.findall(r"[a-z0-9_./-]+", term))
        if term_tokens and len(prompt_tokens & term_tokens) == len(term_tokens):
            score += 1.0

    if tool.always_load:
        score += 0.25

    return score


def _classify_from_index(prompt: str, project_dir: Any = None) -> dict[str, Any] | None:
    """Classify the prompt against the MCP index to find the best resource."""
    try:
        from oats.mcp.index import load_index
        index = load_index(project_dir)
        if index is None:
            return None
        results = index.search(prompt, top_k=1)
        if not results:
            return None
        score, entry = results[0]
        if score < 0.1:
            return None
        result = entry.to_dict()
        result["score"] = score
        return result
    except Exception:
        return None


def _search_index(
    prompt: str,
    project_dir: Any = None,
    top_k: int = 5,
) -> list[tuple[float, dict[str, Any]]]:
    """Search the index and return scored results."""
    try:
        from oats.mcp.index import load_index
        index = load_index(project_dir)
        if index is None:
            return []
        results = index.search(prompt, top_k=top_k)
        return [(score, entry.to_dict()) for score, entry in results]
    except Exception:
        return []
