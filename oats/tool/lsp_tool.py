"""
LSP-backed code intelligence tool.

Provides :class:`LSPTool` which queries a local Language Server Protocol
server for code intelligence operations including go-to-definition,
find-references, hover information, diagnostics, and symbol search.
"""
from __future__ import annotations

import aiofiles
from pathlib import Path
from typing import Any

from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.lsp.client import (
    detect_server_command,
    detect_workspace_server_command,
    format_diagnostics_summary,
    get_lsp_manager,
    path_to_uri,
    uri_to_path,
)
from oats.log import cl

log = cl('tool.lsp')


class LSPTool(Tool):
    """Query a local Language Server Protocol (LSP) server for code intelligence.

    Supports operations such as go-to-definition, find-references, hover
    information, diagnostics, and symbol search. Automatically detects the
    appropriate language server for the file type.

    Example:
        ::

            lsp operation="definition" file_path="src/main.py" line=10 column=5
            lsp operation="workspace_symbols" query="MyClass"
    """

    @property
    def name(self) -> str:
        return "lsp"

    @property
    def aliases(self) -> list[str]:
        return ["code_intel", "language_server"]

    @property
    def keywords(self) -> list[str]:
        return [
            "go to definition",
            "find references",
            "hover symbol",
            "document symbols",
            "workspace symbols",
            "lsp",
        ]

    @property
    def description(self) -> str:
        return """Use a local Language Server Protocol server for code intelligence.

Supported operations:
- definition
- references
- hover
- diagnostics
- document_symbols
- workspace_symbols

Requires an appropriate language server installed locally for the file type.
"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "definition",
                        "references",
                        "hover",
                        "diagnostics",
                        "document_symbols",
                        "workspace_symbols",
                    ],
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to the file for file-scoped operations",
                },
                "line": {
                    "type": "integer",
                    "description": "1-based line number for cursor-based operations",
                },
                "column": {
                    "type": "integer",
                    "description": "1-based column number for cursor-based operations",
                },
                "query": {
                    "type": "string",
                    "description": "Search query for workspace_symbols",
                },
                "include_declaration": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include declarations when finding references",
                },
            },
            "required": ["operation"],
        }

    def is_concurrency_safe(self, args: dict[str, Any] | None = None) -> bool:
        """LSP queries are read-only and safe to run concurrently.

        Returns:
            ``True`` — LSP operations do not modify files.
        """
        return True

    @property
    def strict(self) -> bool:
        """Enforce strict parameter validation for LSP operations."""
        return True

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute an LSP operation (definition, references, hover, etc.).

        Detects the appropriate language server for the file type, syncs the
        file content, and runs the requested operation.

        Args:
            args: Must contain ``operation`` (str). May contain ``file_path`` (str),
                ``line`` (int), ``column`` (int), ``query`` (str), and
                ``include_declaration`` (bool).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the formatted LSP response.
        """
        operation = args.get("operation")
        file_path = args.get("file_path")
        line = int(args.get("line", 1))
        column = int(args.get("column", 1))
        query = args.get("query", "")
        include_declaration = bool(args.get("include_declaration", False))

        if operation not in {
            "definition",
            "references",
            "hover",
            "diagnostics",
            "document_symbols",
            "workspace_symbols",
        }:
            return ToolResult(title="LSP", output="", error="Unsupported LSP operation")

        path: Path | None = None
        if operation != "workspace_symbols":
            if not file_path:
                return ToolResult(title="LSP", output="", error="file_path is required")
            path = Path(file_path)
            if not path.is_absolute():
                path = ctx.working_dir / path
            path = path.resolve()
            if not path.exists():
                return ToolResult(title="LSP", output="", error=f"File not found: {path}")

        root_dir = ctx.project_dir
        if path is not None:
            command = detect_server_command(path)
            if not command:
                return ToolResult(
                    title="LSP",
                    output="",
                    error=(
                        f"No LSP server detected for {path.suffix or 'this file type'}. "
                        "Install a language server or set a CODER_LSP_SERVER_* env var."
                    ),
                )
            manager = get_lsp_manager()
            instance = manager.get_instance(root_dir, command)
            async with aiofiles.open(path, "r", encoding="utf-8", errors="replace") as f:
                content = await f.read()
            await instance.sync_file(path, content)
            result = await self._run_file_operation(
                instance=instance,
                operation=operation,
                path=path,
                line=line,
                column=column,
                include_declaration=include_declaration,
            )
        else:
            command = detect_workspace_server_command(root_dir)
            if not command:
                return ToolResult(
                    title="LSP",
                    output="",
                    error=(
                        "No workspace LSP server detected. "
                        "Set a suitable CODER_LSP_SERVER_* env var."
                    ),
                )
            manager = get_lsp_manager()
            instance = manager.get_instance(root_dir, command)
            result = await instance.request("workspace/symbol", {"query": query})

        return ToolResult(
            title=f"LSP: {operation}",
            output=self._format_result(operation, result, path),
            metadata={"operation": operation, "file_path": str(path) if path else None},
        )

    async def _run_file_operation(
        self,
        instance,
        operation: str,
        path: Path,
        line: int,
        column: int,
        include_declaration: bool,
    ) -> Any:
        """Run a file-scoped LSP operation against the language server.

        Dispatches to the appropriate LSP method based on the operation name.

        Args:
            instance: The LSP server instance.
            operation: One of ``definition``, ``references``, ``hover``,
                ``diagnostics``, or ``document_symbols``.
            path: The file path.
            line: 1-based line number.
            column: 1-based column number.
            include_declaration: Whether to include declarations for references.

        Returns:
            The raw LSP response.
        """
        doc = {"uri": path_to_uri(path)}

        if operation == "definition":
            return await instance.request(
                "textDocument/definition",
                {"textDocument": doc, "position": position},
            )
        if operation == "references":
            return await instance.request(
                "textDocument/references",
                {
                    "textDocument": doc,
                    "position": position,
                    "context": {"includeDeclaration": include_declaration},
                },
            )
        if operation == "hover":
            return await instance.request(
                "textDocument/hover",
                {"textDocument": doc, "position": position},
            )
        if operation == "diagnostics":
            return await instance.collect_diagnostics(path)
        if operation == "document_symbols":
            return await instance.request(
                "textDocument/documentSymbol",
                {"textDocument": doc},
            )
        raise RuntimeError(f"Unsupported LSP operation: {operation}")

    def _format_result(self, operation: str, result: Any, path: Path | None = None) -> str:
        """Format a raw LSP response into a human-readable string.

        Dispatches to the appropriate formatter based on the operation type.

        Args:
            operation: The LSP operation name.
            result: The raw LSP response.
            path: Optional file path for diagnostics formatting.

        Returns:
            A formatted string suitable for display.
        """
        if result is None:
            return "No result."
        if operation == "hover":
            return self._format_hover(result)
        if operation == "diagnostics":
            return format_diagnostics_summary(path or Path("."), result) or "No diagnostics."
        if operation in {"definition", "references"}:
            return self._format_locations(result)
        if operation == "document_symbols":
            return self._format_document_symbols(result)
        if operation == "workspace_symbols":
            return self._format_workspace_symbols(result)
        return str(result)

    def _format_hover(self, result: Any) -> str:
        """Format a hover response into a readable string.

        Handles plain strings, markdown content dicts, and lists of content items.

        Args:
            result: The raw hover response from the LSP server.

        Returns:
            The hover content as a string.
        """
        contents = result.get("contents") if isinstance(result, dict) else result
        if isinstance(contents, str):
            return contents
        if isinstance(contents, dict):
            if "value" in contents:
                return str(contents["value"])
            return str(contents)
        if isinstance(contents, list):
            parts = []
            for item in contents:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "value" in item:
                    parts.append(str(item["value"]))
                else:
                    parts.append(str(item))
            return "\n\n".join(parts)
        return str(contents)

    def _format_locations(self, result: Any) -> str:
        """Format definition or references locations into a readable list.

        Each location is rendered as ``file_path:line:column``.

        Args:
            result: A single location dict or a list of location dicts.

        Returns:
            A newline-separated list of location strings.
        """
        if isinstance(result, dict):
            result = [result]
        if not isinstance(result, list) or not result:
            return "No locations found."
        lines = []
        for item in result:
            uri = (
                item.get("uri")
                or item.get("targetUri")
                or item.get("targetURI")
                or ""
            )
            range_obj = item.get("range") or item.get("targetSelectionRange") or {}
            start = range_obj.get("start", {})
            line = int(start.get("line", 0)) + 1
            char = int(start.get("character", 0)) + 1
            lines.append(f"{uri_to_path(uri)}:{line}:{char}")
        return "\n".join(lines)

    def _format_document_symbols(self, result: Any) -> str:
        """Format document symbols into a hierarchical tree.

        Walks the symbol tree recursively, indenting children and showing
        the symbol kind and line number.

        Args:
            result: A list of document symbol dicts.

        Returns:
            A formatted tree of symbols.
        """
        if not isinstance(result, list) or not result:
            return "No symbols found."
        lines: list[str] = []

        def walk(symbols: list[dict[str, Any]], depth: int = 0) -> None:
            """Recursively walk the symbol tree, appending formatted entries to *lines*."""
            prefix = "  " * depth
            for symbol in symbols:
                name = symbol.get("name", "<unnamed>")
                kind = symbol.get("kind", "?")
                location = symbol.get("location", {})
                range_obj = symbol.get("range") or location.get("range") or {}
                start = range_obj.get("start", {})
                line = int(start.get("line", 0)) + 1 if start else None
                suffix = f" (kind={kind}, line={line})" if line is not None else f" (kind={kind})"
                lines.append(f"{prefix}- {name}{suffix}")
                children = symbol.get("children")
                if isinstance(children, list) and children:
                    walk(children, depth + 1)

        walk(result)
        return "\n".join(lines)

    def _format_workspace_symbols(self, result: Any) -> str:
        """Format workspace symbols into a flat list.

        Shows up to 100 symbols with their name, kind, file path, and line number.

        Args:
            result: A list of workspace symbol dicts.

        Returns:
            A formatted list of workspace symbols.
        """
        if not isinstance(result, list) or not result:
            return "No workspace symbols found."
        lines = []
        for symbol in result[:100]:
            name = symbol.get("name", "<unnamed>")
            kind = symbol.get("kind", "?")
            location = symbol.get("location", {})
            uri = location.get("uri", "")
            range_obj = location.get("range", {})
            start = range_obj.get("start", {})
            line = int(start.get("line", 0)) + 1 if start else 1
            lines.append(f"- {name} (kind={kind}) — {uri_to_path(uri)}:{line}")
        return "\n".join(lines)
