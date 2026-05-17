"""
WebFetch tool for fetching and processing web content.

Provides :class:`WebFetchTool` which fetches content from URLs and converts
HTML to simplified plain text/markdown. Content is truncated if it exceeds
the maximum length.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse
import httpx
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.webfetch')


class WebFetchTool(Tool):
    """Fetch content from a URL and convert it to plain text/markdown.

    Validates the URL, fetches the content via HTTP, and converts HTML
    to simplified text. Content is truncated if it exceeds the maximum
    length (100KB).

    Example:
        ::

            webfetch url="https://docs.python.org/3/library/asyncio.html"
    """

    MAX_CONTENT_LENGTH = 100000
    TIMEOUT = 30

    @property
    def name(self) -> str:
        return "webfetch"

    @property
    def description(self) -> str:
        return """Fetch content from a URL and process it.

Use this to:
- Retrieve documentation from URLs
- Fetch API responses
- Get content from web pages

The content is converted to plain text/markdown for easier processing."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch content from",
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional prompt to describe what information to extract",
                },
            },
            "required": ["url"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Fetch content from a URL and convert it to plain text/markdown.

        Validates the URL, fetches the content via HTTP, and converts HTML to
        simplified text. Content is truncated if it exceeds the maximum length.

        Args:
            args: Must contain ``url`` (str). May contain ``prompt`` (str) for
                describing what information to extract.
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the fetched content and metadata.
        """
        url = args.get("url", "")
        prompt = args.get("prompt", "")

        if not url:
            return ToolResult(
                title="WebFetch",
                output="",
                error="No URL provided",
            )

        # Validate URL
        try:
            parsed = urlparse(url)
            if not parsed.scheme:
                url = f"https://{url}"
            elif parsed.scheme == "http":
                url = url.replace("http://", "https://", 1)
        except Exception as e:
            return ToolResult(
                title="WebFetch",
                output="",
                error=f"Invalid URL: {e}",
            )

        try:
            async with httpx.AsyncClient(
                timeout=self.TIMEOUT,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; OpenCode/1.0)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                content = response.text

                # Convert HTML to simplified text
                if "text/html" in content_type:
                    content = self._html_to_text(content)

                # Truncate if too long
                if len(content) > self.MAX_CONTENT_LENGTH:
                    content = content[: self.MAX_CONTENT_LENGTH]
                    content += "\n\n[Content truncated]"

                output = f"URL: {url}\n\n{content}"

                if prompt:
                    output = f"Prompt: {prompt}\n\n{output}"

                return ToolResult(
                    title=f"WebFetch: {parsed.netloc}",
                    output=output,
                    metadata={
                        "url": url,
                        "content_type": content_type,
                        "content_length": len(content),
                        "status_code": response.status_code,
                    },
                )

        except httpx.TimeoutException:
            return ToolResult(
                title="WebFetch",
                output="",
                error=f"Request timed out after {self.TIMEOUT} seconds",
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                title="WebFetch",
                output="",
                error=f"HTTP error {e.response.status_code}: {e.response.reason_phrase}",
            )
        except Exception as e:
            return ToolResult(
                title="WebFetch",
                output="",
                error=f"Failed to fetch URL: {e}",
            )

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text with basic markdown formatting.

        Strips script/style elements, converts headers, links, bold, italic,
        code blocks, lists, and paragraphs to markdown equivalents. Removes
        remaining HTML tags and decodes common HTML entities.

        Args:
            html: The raw HTML content.

        Returns:
            The text content with basic markdown formatting.
        """
        # Remove script and style elements
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

        # Convert headers to markdown
        for i in range(1, 7):
            html = re.sub(
                rf"<h{i}[^>]*>(.*?)</h{i}>",
                rf"\n{'#' * i} \1\n",
                html,
                flags=re.DOTALL | re.IGNORECASE,
            )

        # Convert links to markdown
        html = re.sub(
            r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
            r"[\2](\1)",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Convert bold/strong
        html = re.sub(r"<(b|strong)[^>]*>(.*?)</\1>", r"**\2**", html, flags=re.DOTALL | re.IGNORECASE)

        # Convert italic/em
        html = re.sub(r"<(i|em)[^>]*>(.*?)</\1>", r"*\2*", html, flags=re.DOTALL | re.IGNORECASE)

        # Convert code
        html = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", html, flags=re.DOTALL | re.IGNORECASE)

        # Convert pre blocks
        html = re.sub(r"<pre[^>]*>(.*?)</pre>", r"\n```\n\1\n```\n", html, flags=re.DOTALL | re.IGNORECASE)

        # Convert lists
        html = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", html, flags=re.DOTALL | re.IGNORECASE)

        # Convert paragraphs and divs to newlines
        html = re.sub(r"<(p|div)[^>]*>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(r"</(p|div)>", "\n", html, flags=re.IGNORECASE)

        # Convert br to newline
        html = re.sub(r"<br[^>]*>", "\n", html, flags=re.IGNORECASE)

        # Remove remaining HTML tags
        html = re.sub(r"<[^>]+>", "", html)

        # Decode common HTML entities
        html = html.replace("&nbsp;", " ")
        html = html.replace("&amp;", "&")
        html = html.replace("&lt;", "<")
        html = html.replace("&gt;", ">")
        html = html.replace("&quot;", '"')
        html = html.replace("&#39;", "'")

        # Clean up whitespace
        html = re.sub(r"\n\s*\n\s*\n", "\n\n", html)
        html = re.sub(r"[ \t]+", " ", html)

        return html.strip()
