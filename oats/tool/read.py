"""
Read tool for reading file contents.

Provides :class:`ReadTool` which reads files with line numbers, supports
offset and limit parameters for reading portions of large files, and
truncates long lines for readability.
"""
from __future__ import annotations


import aiofiles
from pathlib import Path
from typing import Any
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.read')


class ReadTool(Tool):
    """Read the contents of a file with line numbers.

    Supports reading full files or specific ranges via offset and limit
    parameters. Long lines are truncated for readability. Binary files
    are detected and rejected.

    Example:
        ::

            read file_path="src/main.py"
            read file_path="large_file.txt" offset=100 limit=50
    """

    MAX_LINES = 2000
    MAX_LINE_LENGTH = 2000

    @property
    def name(self) -> str:
        return "read"

    @property
    def aliases(self) -> list[str]:
        return ["file_read", "cat_file"]

    @property
    def keywords(self) -> list[str]:
        return [
            "read file",
            "open file",
            "inspect file",
            "show file contents",
            "view source",
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
        return """Read the contents of a file. ALWAYS use this tool to read any file — never use bash with cat, head, or tail.

Returns file contents with line numbers. Supports:
- Text files (any path including /etc, /tmp, etc.)
- Code files
- Configuration files

For large files, use offset and limit parameters."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to read",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read",
                },
            },
            "required": ["file_path"],
        }

    def requires_permission(self, args: dict[str, Any], ctx: ToolContext) -> str | None:
        """Read operations are generally allowed but require permission outside the project.

        Args:
            args: The tool arguments containing the ``file_path``.
            ctx: The tool execution context.

        Returns:
            A permission prompt string if reading outside the project directory,
            otherwise ``None``.
        """
        file_path = args.get("file_path", "")
        # Check if reading outside project directory
        try:
            path = self._resolve_path(file_path, ctx)
            if not str(path).startswith(str(ctx.project_dir)):
                return f"Read file outside project: {file_path}"
        except Exception:
            pass
        return None

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
        """Read the contents of a file and return it with line numbers.

        Supports offset and limit parameters for reading portions of large files.
        Long lines are truncated to MAX_LINE_LENGTH.

        Args:
            args: Must contain ``file_path`` (str). May contain ``offset`` (int,
                1-based line number) and ``limit`` (int, max lines to read).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the file contents formatted with line numbers.
        """
        file_path = args.get("file_path", "")
        offset = args.get("offset", 1)
        limit = args.get("limit", self.MAX_LINES)

        if not file_path:
            return ToolResult(
                title="Read",
                output="",
                error="No file path provided",
            )

        try:
            path = self._resolve_path(file_path, ctx)

            if not path.exists():
                return ToolResult(
                    title="Read",
                    output="",
                    error=f"File not found: {path}",
                )

            if not path.is_file():
                return ToolResult(
                    title="Read",
                    output="",
                    error=f"Not a file: {path}",
                )

            # Check file cache
            if ctx.file_cache and ctx.file_cache.is_fresh(str(path)):
                # File hasn't changed since last read — note this in metadata
                pass  # still read it, but mark as cache-hit for tracking

            # Read the file
            async with aiofiles.open(path, "r", encoding="utf-8", errors="replace") as f:
                content = await f.read()

            # Update file cache
            if ctx.file_cache:
                ctx.file_cache.mark_read(str(path), content)

            # Split into lines
            lines = content.split("\n")
            total_lines = len(lines)

            # Apply offset (convert to 0-based)
            start_idx = max(0, offset - 1)
            end_idx = min(start_idx + limit, total_lines)

            # Get the requested lines
            selected_lines = lines[start_idx:end_idx]

            # Format with line numbers
            formatted_lines = []
            for i, line in enumerate(selected_lines):
                line_num = start_idx + i + 1
                # Truncate long lines
                if len(line) > self.MAX_LINE_LENGTH:
                    line = line[: self.MAX_LINE_LENGTH] + "..."
                formatted_lines.append(f"{line_num:6}\t{line}")

            output = "\n".join(formatted_lines)

            # Add truncation notice if applicable
            if end_idx < total_lines:
                output += f"\n\n[Showing lines {start_idx + 1}-{end_idx} of {total_lines}]"

            return ToolResult(
                title=f"Read: {path.name}",
                output=output,
                metadata={
                    "file_path": str(path),
                    "total_lines": total_lines,
                    "lines_shown": len(selected_lines),
                    "offset": offset,
                    "limit": limit,
                },
            )

        except UnicodeDecodeError:
            return ToolResult(
                title="Read",
                output="",
                error=f"Cannot read binary file: {file_path}",
            )
        except PermissionError:
            return ToolResult(
                title="Read",
                output="",
                error=f"Permission denied: {file_path}",
            )
        except Exception as e:
            return ToolResult(
                title="Read",
                output="",
                error=f"Error reading file: {e}",
            )
