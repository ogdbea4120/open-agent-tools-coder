"""
Write tool for creating and overwriting files.

Provides :class:`WriteTool` which writes content to files, creating parent
directories as needed. Optionally syncs with the LSP server for diagnostics
if the feature is enabled.
"""
from __future__ import annotations


import aiofiles
from pathlib import Path
from typing import Any
from oats.core.features import lsp_tools_candidate_enabled
from oats.lsp.client import sync_file_and_collect_diagnostics
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.write')


class WriteTool(Tool):
    """Write content to a file, creating it or overwriting if it exists.

    Creates parent directories as needed. Optionally syncs with the LSP
    server for diagnostics if the feature is enabled.

    Example:
        ::

            write file_path="src/new_module.py" content="def hello(): ..."
    """

    @property
    def name(self) -> str:
        return "write"

    @property
    def aliases(self) -> list[str]:
        return ["file_write", "create_file", "overwrite_file"]

    @property
    def keywords(self) -> list[str]:
        return [
            "write file",
            "create file",
            "overwrite file",
            "save file contents",
        ]

    @property
    def always_load(self) -> bool:
        return True

    @property
    def strict(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return """Write content to a file.

Creates the file if it doesn't exist, or overwrites if it does.
Creates parent directories as needed.

Use the 'edit' tool for making changes to existing files."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["file_path", "content"],
        }

    def requires_permission(self, args: dict[str, Any], ctx: ToolContext) -> str | None:
        """Write operations always require user permission.

        Args:
            args: The tool arguments containing the ``file_path``.
            ctx: The tool execution context.

        Returns:
            A permission prompt string describing the file to be written.
        """
        file_path = args.get("file_path", "")
        return f"Write file: {file_path}"

    def _resolve_path(self, file_path: str, ctx: ToolContext) -> Path:
        """Resolve a file path relative to the tool context's working directory.

        Args:
            file_path: The file path (absolute or relative).
            ctx: The tool execution context.

        Returns:
            The resolved absolute :class:`pathlib.Path`.
        """
        path = Path(file_path)
        if not path.is_absolute():
            path = ctx.working_dir / path
        return path.resolve()

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Write content to a file, creating it or overwriting if it exists.

        Creates parent directories as needed. Optionally syncs with the LSP
        server for diagnostics if the feature is enabled.

        Args:
            args: Must contain ``file_path`` (str) and ``content`` (str).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the file path, line count, and optional LSP diagnostics.
        """
        file_path = args.get("file_path", "")
        content = args.get("content", "")

        if not file_path:
            return ToolResult(
                title="Write",
                output="",
                error="No file path provided",
            )

        try:
            path = self._resolve_path(file_path, ctx)

            # Track if this is a new file or overwrite
            is_new = not path.exists()

            # Create parent directories
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write the file
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(content)

            # Count lines
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

            # Update file cache
            if ctx.file_cache:
                ctx.file_cache.mark_written(str(path))

            lsp_synced = False
            lsp_diagnostics = None
            if lsp_tools_candidate_enabled():
                try:
                    lsp_synced, lsp_diagnostics = await sync_file_and_collect_diagnostics(
                        ctx.project_dir, path, content
                    )
                except Exception:
                    lsp_synced = False
                    lsp_diagnostics = None

            action = "Created" if is_new else "Wrote"
            output = f"{action} {path} ({line_count} lines)"
            if lsp_diagnostics:
                output = f"{output}\n\n{lsp_diagnostics}"
            return ToolResult(
                title=f"Write: {path.name}",
                output=output,
                metadata={
                    "file_path": str(path),
                    "is_new": is_new,
                    "line_count": line_count,
                    "byte_count": len(content.encode("utf-8")),
                    "lsp_synced": lsp_synced,
                    "lsp_diagnostics": lsp_diagnostics,
                },
            )

        except PermissionError:
            return ToolResult(
                title="Write",
                output="",
                error=f"Permission denied: {file_path}",
            )
        except Exception as e:
            return ToolResult(
                title="Write",
                output="",
                error=f"Error writing file: {e}",
            )
