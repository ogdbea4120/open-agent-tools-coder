"""
WebSearch tool for searching the web.

Provides :class:`WebSearchTool` which searches the web using multiple
backends in priority order: SerpAPI, Brave, Tavily, Playwright/DuckDuckGo,
and DuckDuckGo instant answer API.
"""

from __future__ import annotations

import os
from typing import Any
import httpx
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.websearch')


class WebSearchTool(Tool):
    """Search the web for information using multiple backends.

    Tries backends in priority order: SerpAPI, Brave, Tavily,
    Playwright/DuckDuckGo, and DuckDuckGo instant answer API.
    The first available backend (based on API key configuration) is used.

    Example:
        ::

            websearch query="Python async best practices"
            websearch query="sphinx documentation" num_results=3
    """

    TIMEOUT = 30
    MAX_RESULTS = 10

    @property
    def name(self) -> str:
        return "websearch"

    @property
    def description(self) -> str:
        return """Search the web for information.

Use this to:
- Find documentation or tutorials
- Research technical topics
- Look up error messages
- Find recent information

Returns search results with titles, URLs, and snippets."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Search the web using the best available backend.

        Tries backends in priority order: SerpAPI → Brave → Tavily →
        Playwright/DuckDuckGo → DuckDuckGo instant answer API.

        Args:
            args: Must contain ``query`` (str). May contain ``num_results`` (int, default 5).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with search results or an error message.
        """
        query = args.get("query", "")
        num_results = min(args.get("num_results", 5), self.MAX_RESULTS)

        if not query:
            return ToolResult(
                title="WebSearch",
                output="",
                error="No search query provided",
            )

        # Try different search backends
        # 1. Try SerpAPI if configured
        serpapi_key = os.environ.get("SERPAPI_API_KEY")
        if serpapi_key:
            return await self._search_serpapi(query, num_results, serpapi_key)

        # 2. Try Brave Search if configured
        brave_key = os.environ.get("BRAVE_SEARCH_API_KEY")
        if brave_key:
            return await self._search_brave(query, num_results, brave_key)

        # 3. Try Tavily if configured
        tavily_key = os.environ.get("TAVILY_API_KEY")
        if tavily_key:
            return await self._search_tavily(query, num_results, tavily_key)

        # 4. Try Playwright-powered browser search (no API key needed)
        try:
            from oats.tool.playwright_search import playwright_search
            results = await playwright_search(query, num_results)
            if results:
                return self._format_results(query, results, "Playwright/DuckDuckGo")
        except ImportError:
            pass  # playwright not installed, fall through
        except Exception:
            pass  # browser search failed, fall through

        # 5. Last resort - DuckDuckGo instant answer API (limited results)
        return await self._search_duckduckgo(query, num_results)

    async def _search_serpapi(
        self, query: str, num_results: int, api_key: str
    ) -> ToolResult:
        """Search using the SerpAPI backend.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return.
            api_key: The SerpAPI API key.

        Returns:
            A :class:`ToolResult` with the search results.
        """
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.get(
                    "https://serpapi.com/search",
                    params={
                        "q": query,
                        "api_key": api_key,
                        "num": num_results,
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("organic_results", [])[:num_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })

                return self._format_results(query, results, "SerpAPI")

        except Exception as e:
            return ToolResult(
                title="WebSearch",
                output="",
                error=f"SerpAPI search failed: {e}",
            )

    async def _search_brave(
        self, query: str, num_results: int, api_key: str
    ) -> ToolResult:
        """Search using the Brave Search API backend.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return.
            api_key: The Brave Search API key.

        Returns:
            A :class:`ToolResult` with the search results.
        """
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": num_results},
                    headers={"X-Subscription-Token": api_key},
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("web", {}).get("results", [])[:num_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("description", ""),
                    })

                return self._format_results(query, results, "Brave Search")

        except Exception as e:
            return ToolResult(
                title="WebSearch",
                output="",
                error=f"Brave Search failed: {e}",
            )

    async def _search_tavily(
        self, query: str, num_results: int, api_key: str
    ) -> ToolResult:
        """Search using the Tavily API backend.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return.
            api_key: The Tavily API key.

        Returns:
            A :class:`ToolResult` with the search results.
        """
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "query": query,
                        "api_key": api_key,
                        "max_results": num_results,
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("results", [])[:num_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", "")[:300],
                    })

                return self._format_results(query, results, "Tavily")

        except Exception as e:
            return ToolResult(
                title="WebSearch",
                output="",
                error=f"Tavily search failed: {e}",
            )

    async def _search_duckduckgo(self, query: str, num_results: int) -> ToolResult:
        """Search using the DuckDuckGo instant answer API (no API key required).

        Returns limited results — primarily an abstract and related topics.

        Args:
            query: The search query string.
            num_results: Maximum number of results to return.

        Returns:
            A :class:`ToolResult` with the search results.
        """
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                # Use DuckDuckGo instant answer API
                response = await client.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_html": 1,
                        "skip_disambig": 1,
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = []

                # Add abstract if available
                if data.get("AbstractText"):
                    results.append({
                        "title": data.get("Heading", "Summary"),
                        "url": data.get("AbstractURL", ""),
                        "snippet": data.get("AbstractText", ""),
                    })

                # Add related topics
                for item in data.get("RelatedTopics", [])[:num_results - len(results)]:
                    if isinstance(item, dict) and item.get("Text"):
                        results.append({
                            "title": item.get("Text", "")[:80],
                            "url": item.get("FirstURL", ""),
                            "snippet": item.get("Text", ""),
                        })

                if not results:
                    return ToolResult(
                        title="WebSearch",
                        output=f"No results found for: {query}\n\nTip: Set SERPAPI_API_KEY, BRAVE_SEARCH_API_KEY, or TAVILY_API_KEY for better results.",
                        metadata={"query": query, "source": "DuckDuckGo"},
                    )

                return self._format_results(query, results, "DuckDuckGo")

        except Exception as e:
            return ToolResult(
                title="WebSearch",
                output="",
                error=f"DuckDuckGo search failed: {e}. Consider setting SERPAPI_API_KEY for better results.",
            )

    def _format_results(
        self, query: str, results: list[dict[str, str]], source: str
    ) -> ToolResult:
        """Format search results into a :class:`ToolResult`.

        Each result is rendered as a numbered entry with title, URL, and snippet.

        Args:
            query: The original search query.
            results: A list of result dicts with ``title``, ``url``, and ``snippet``.
            source: The name of the search backend used.

        Returns:
            A :class:`ToolResult` with the formatted results.
        """
        if not results:
            return ToolResult(
                title="WebSearch",
                output=f"No results found for: {query}",
                metadata={"query": query, "source": source, "num_results": 0},
            )

        output_lines = [f"Search results for: {query}\n"]

        for i, result in enumerate(results, 1):
            output_lines.append(f"{i}. **{result['title']}**")
            if result["url"]:
                output_lines.append(f"   URL: {result['url']}")
            if result["snippet"]:
                output_lines.append(f"   {result['snippet'][:200]}")
            output_lines.append("")

        return ToolResult(
            title=f"WebSearch: {query[:30]}",
            output="\n".join(output_lines),
            metadata={
                "query": query,
                "source": source,
                "num_results": len(results),
            },
        )
