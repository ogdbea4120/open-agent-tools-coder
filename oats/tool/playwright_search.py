"""
Playwright-powered web search — no API keys required.

Uses a headless Chromium browser to search Bing (primary) or
DuckDuckGo (fallback) and extract real web results with titles,
URLs, and snippets. Registered alongside :class:`WebSearchTool` and
wired as a fallback when no search API keys are configured.

Provides:

- :class:`PlaywrightSearchTool` — Tool class for headless browser search.
- :func:`playwright_search` — Low-level async function for browser-based search.
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote_plus
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.pw_search')


# ── Bing result extraction ───────────────────────────────────────────

_JS_BING_RESULTS = """() => {
    const items = [];
    document.querySelectorAll('li.b_algo').forEach(el => {
        const linkEl = el.querySelector('h2 a');
        const snippetEl = el.querySelector('.b_caption p, .b_algoSlug');
        if (linkEl) {
            const title = (linkEl.innerText || '').trim();
            const url = linkEl.href || '';
            const snippet = snippetEl
                ? (snippetEl.innerText || '').trim().substring(0, 300)
                : '';
            if (title && url) {
                items.push({ title: title.substring(0, 150), url, snippet });
            }
        }
    });
    return items;
}"""

# ── DuckDuckGo HTML-only fallback ────────────────────────────────────

_JS_DDG_RESULTS = """() => {
    const items = [];
    document.querySelectorAll('.result, article').forEach(el => {
        const linkEl = el.querySelector('.result__a, a[data-testid="result-title-a"], h2 a');
        const snippetEl = el.querySelector('.result__snippet, [data-testid="result-snippet"]');
        if (linkEl) {
            const title = (linkEl.innerText || '').trim();
            const url = linkEl.href || '';
            const snippet = snippetEl
                ? (snippetEl.innerText || '').trim().substring(0, 300)
                : '';
            if (title && url && !url.startsWith('javascript:')) {
                items.push({ title: title.substring(0, 150), url, snippet });
            }
        }
    });
    return items;
}"""


async def playwright_search(query: str, num_results: int = 5) -> list[dict[str, str]]:
    """Search the web via headless Chromium and return result dicts.

    Tries Bing first, falls back to DuckDuckGo HTML if Bing fails.
    Each result dict has keys: ``title``, ``url``, ``snippet``.

    Raises ``ImportError`` if playwright is not installed.
    """
    from playwright.async_api import async_playwright

    encoded = quote_plus(query)

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()

        results: list[dict[str, str]] = []

        # ── Try Bing first ───────────────────────────────────────────
        try:
            await page.goto(
                f"https://www.bing.com/search?q={encoded}",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            await asyncio.sleep(1.5)
            results = await page.evaluate(_JS_BING_RESULTS)
        except Exception:
            pass

        # ── Fallback: DuckDuckGo ─────────────────────────────────────
        if not results:
            try:
                await page.goto(
                    f"https://html.duckduckgo.com/html/?q={encoded}",
                    wait_until="domcontentloaded",
                    timeout=15_000,
                )
                await asyncio.sleep(1.5)
                results = await page.evaluate(_JS_DDG_RESULTS)
            except Exception:
                pass

        await browser.close()
    finally:
        await pw.stop()

    # De-duplicate by URL and cap at requested count
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for r in results:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)
        if len(unique) >= num_results:
            break

    return unique


# ── Tool class ───────────────────────────────────────────────────────

class PlaywrightSearchTool(Tool):
    """Search the web using a headless Chromium browser (no API keys needed).

    Uses Playwright to launch a headless browser, search Bing (primary) or
    DuckDuckGo (fallback), and extract real web results with titles, URLs,
    and snippets. Registered alongside :class:`WebSearchTool` and wired as
    a fallback when no search API keys are configured.

    Example:
        ::

            playwright_search query="Python async best practices"
    """

    @property
    def name(self) -> str:
        return "playwright_search"

    @property
    def description(self) -> str:
        return (
            "Search the web using a headless Chromium browser.  "
            "No API keys required.  Searches DuckDuckGo and returns "
            "real results with titles, URLs, and snippets.\n\n"
            "Use this when no search API keys are configured or when "
            "you need to search the web and other search tools are "
            "unavailable."
        )

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
                    "description": "Number of results (default 5, max 10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    @property
    def keywords(self) -> list[str]:
        return ["search", "web", "google", "duckduckgo", "find", "lookup"]

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Search the web using a headless Chromium browser.

        Delegates to :func:`playwright_search` which tries Bing first, then
        DuckDuckGo as a fallback.

        Args:
            args: Must contain ``query`` (str). May contain ``num_results`` (int, default 5).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with search results or an error message.
        """
        query = args.get("query", "")
        num_results = min(args.get("num_results", 5), 10)

        if not query:
            return ToolResult(
                title="PlaywrightSearch",
                output="",
                error="No search query provided",
            )

        try:
            results = await playwright_search(query, num_results)
        except ImportError:
            return ToolResult(
                title="PlaywrightSearch",
                output="",
                error=(
                    "playwright is not installed. "
                    "Install with: pip install playwright && playwright install chromium"
                ),
            )
        except Exception as e:
            return ToolResult(
                title="PlaywrightSearch",
                output="",
                error=f"Search failed: {e}",
            )

        if not results:
            return ToolResult(
                title=f"PlaywrightSearch: {query[:30]}",
                output="No results found.",
                metadata={"query": query, "source": "playwright_duckduckgo", "num_results": 0},
            )

        # Format results as markdown
        lines: list[str] = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**")
            lines.append(f"   {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append("")

        return ToolResult(
            title=f"PlaywrightSearch: {query[:30]}",
            output="\n".join(lines),
            metadata={
                "query": query,
                "source": "playwright_duckduckgo",
                "num_results": len(results),
            },
        )
