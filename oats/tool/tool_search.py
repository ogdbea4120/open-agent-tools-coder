"""
Tool discovery tool for deferred loading of non-core tool schemas.

Provides :class:`ToolSearchTool` which searches the tool catalog and returns
callable schemas for matched tools. Supports exact-select queries (``select:``
prefix) and fuzzy natural-language search.

Helper functions:

- :func:`_tokenize` — Split text into lowercase alphanumeric tokens for fuzzy matching.
"""
from __future__ import annotations

import json
import re
from typing import Any
from oats.tool.registry import Tool, ToolContext, ToolResult, list_tools
from oats.log import cl

log = cl('tool.search')


def _tokenize(text: str) -> set[str]:
    """Split *text* into lowercase alphanumeric tokens for fuzzy matching.

    Strips punctuation and returns a set of word-like tokens (alphanumeric
    sequences that may include underscores, dots, slashes, and hyphens).

    Args:
        text: The input text to tokenize.

    Returns:
        A set of lowercase token strings.
    """
    return set(re.findall(r"[a-z0-9_./-]+", text.lower()))


class ToolSearchTool(Tool):
    """Search the tool catalog and return callable schemas for matched tools.

    Supports two query modes:

    1. **Exact-select** — prefix with ``select:`` and comma-separated tool names
    2. **Fuzzy search** — natural language query scored against tool names,
       descriptions, aliases, and keywords

    Example:
        ::

            tool_search query="select:deploy_app_with_docker_compose,get_app_logs"
            tool_search query="deploy docker app"
    """

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def aliases(self) -> list[str]:
        return ["search_tools", "find_tool", "load_tool_schema"]

    @property
    def keywords(self) -> list[str]:
        return [
            "find tool",
            "load tool schema",
            "discover available tools",
            "search tool catalog",
        ]

    @property
    def always_load(self) -> bool:
        return True

    @property
    def strict(self) -> bool:
        return True

    def is_concurrency_safe(self, args: dict[str, Any] | None = None) -> bool:
        return True

    @property
    def description(self) -> str:
        return """Search the full tool catalog and return callable schemas for matched tools.

Use this when the exact tool you need is not already loaded in the current turn.
This tool is especially useful with local models where we keep the active tool set
focused and load less-common tool schemas on demand.

Query examples:
- "select:deploy_app_with_docker_compose,get_app_logs"
- "deploy docker app"
- "certificate expiration domain ssl"
"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Exact-select query or natural-language search for tools",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of tools to return",
                    "default": 8,
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Search the tool catalog and return schemas for matched tools.

        Args:
            args: Must contain ``query`` (str) and optionally ``max_results`` (int).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with matched tool schemas or an error message.
        """
        query = str(args.get("query", "")).strip()
        max_results = max(1, min(int(args.get("max_results", 8)), 20))

        if not query:
            return ToolResult(
                title="ToolSearch",
                output="",
                error="No query provided",
            )

        tools = list_tools()
        matched = self._match_tools(query, tools, max_results=max_results)

        if not matched:
            return ToolResult(
                title="ToolSearch",
                output=f"No tools matched query: {query}",
                metadata={"matched_tool_names": []},
            )

        lines = [
            "Matched tool schemas:",
            "",
        ]
        schema_payload: list[dict[str, Any]] = []

        for tool in matched:
            schema = {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            schema_payload.append(schema)
            lines.append(f"- {tool.name}")
            lines.append(json.dumps(schema, indent=2, sort_keys=True))

        return ToolResult(
            title="ToolSearch",
            output="\n".join(lines),
            metadata={
                "matched_tool_names": [tool.name for tool in matched],
                "schemas": schema_payload,
                "query": query,
            },
        )

    def _match_tools(
        self,
        query: str,
        tools: list[Tool],
        max_results: int,
    ) -> list[Tool]:
        """Match tools against a query string.

        Supports two modes:
        - **Exact select**: If the query starts with ``select:``, match tools by
          name or alias exactly (comma-separated).
        - **Fuzzy search**: Tokenize the query and score each tool by name,
          alias, keyword, and description overlap.

        Args:
            query: The search query string.
            tools: The list of tools to search through.
            max_results: Maximum number of results to return.

        Returns:
            A list of matching tools, sorted by relevance score.
        """
        query_lower = query.lower()
        if query_lower.startswith("select:"):
            wanted = {
                item.strip()
                for item in query_lower.split(":", 1)[1].split(",")
                if item.strip()
            }
            exact = []
            for tool in tools:
                names = {tool.name.lower(), *(alias.lower() for alias in tool.aliases)}
                if names & wanted:
                    exact.append(tool)
            return exact[:max_results]

        query_tokens = _tokenize(query)
        scored: list[tuple[float, Tool]] = []
        for tool in tools:
            haystack = " ".join(
                [
                    tool.name,
                    tool.description,
                    *tool.aliases,
                    *tool.keywords,
                ]
            ).lower()
            haystack_tokens = _tokenize(haystack)
            score = 0.0
            if tool.name.lower() in query_lower:
                score += 4.0
            for alias in tool.aliases:
                if alias.lower() in query_lower:
                    score += 3.0
            for keyword in tool.keywords:
                if keyword.lower() in query_lower:
                    score += 2.5
            overlap = len(query_tokens & haystack_tokens)
            score += overlap
            if score > 0:
                scored.append((score, tool))

        scored.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        return [tool for _, tool in scored[:max_results]]
