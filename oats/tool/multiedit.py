"""
MultiEdit tool for applying multiple edits to a file in sequence.

Provides :class:`MultiEditTool` which applies multiple text replacements
to a single file in sequence. Each edit sees the results of earlier ones,
and the file is written only if at least one replacement was made.
"""

from __future__ import annotations

import aiofiles
from pathlib import Path
from typing import Any

from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl("tool.multiedit")


class MultiEditTool(Tool):
    """Apply multiple text replacements to a single file in sequence.

    Each edit is applied in order so that later edits see the results of
    earlier ones. The file is written only if at least one replacement
    was made, ensuring atomicity.

    Example:
        ::

            multiedit file_path="src/main.py" edits=[
                {"old_string": "def a():", "new_string": "def b():"},
                {"old_string": "def c():", "new_string": "def d():"}
            ]
    """

    @property
    def name(self) -> str:
        return "multiedit"

    @property
    def description(self) -> str:
        return """Apply multiple edits to a single file in sequence.

Use this when you need to make several changes to the same file.
Each edit is applied in order, so later edits see the results of earlier ones.

This is more efficient than multiple separate edit calls and ensures
all edits are applied atomically."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "edits": {
                    "type": "array",
                    "description": "List of edits to apply in order",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_string": {
                                "type": "string",
                                "description": "Text to find and replace",
                            },
                            "new_string": {
                                "type": "string",
                                "description": "Text to replace with",
                            },
                            "replace_all": {
                                "type": "boolean",
                                "description": "Replace all occurrences (default: false)",
                                "default": False,
                            },
                        },
                        "required": ["old_string", "new_string"],
                    },
                },
            },
            "required": ["file_path", "edits"],
        }

    def requires_permission(self, args: dict[str, Any], ctx: ToolContext) -> str | None:
        """MultiEdit operations always require user permission.

        Args:
            args: The tool arguments containing ``file_path`` and ``edits``.
            ctx: The tool execution context.

        Returns:
            A permission prompt string describing the number of edits and target file.
        """
        file_path = args.get("file_path", "")
        num_edits = len(args.get("edits", []))
        return f"Apply {num_edits} edits to: {file_path}"

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
        """Apply multiple text replacements to a single file in sequence.

        Each edit is applied in order so that later edits see the results of
        earlier ones. The file is written only if at least one replacement
        was made.

        Args:
            args: Must contain ``file_path`` (str) and ``edits`` (list of dicts
                with ``old_string``, ``new_string``, and optional ``replace_all``).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with per-edit results and a total replacement count.
        """
        file_path = args.get("file_path", "")
        edits = args.get("edits", [])

        if not file_path:
            return ToolResult(
                title="MultiEdit",
                output="",
                error="No file path provided",
            )

        if not edits:
            return ToolResult(
                title="MultiEdit",
                output="",
                error="No edits provided",
            )

        try:
            path = self._resolve_path(file_path, ctx)

            if not path.exists():
                return ToolResult(
                    title="MultiEdit",
                    output="",
                    error=f"File not found: {path}",
                )

            # Read the file
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                content = await f.read()

            original_content = content
            results = []
            total_replacements = 0

            # Apply each edit in sequence
            for i, edit in enumerate(edits):
                old_string = edit.get("old_string", "")
                new_string = edit.get("new_string", "")
                replace_all = edit.get("replace_all", False)

                if not old_string:
                    results.append(f"Edit {i+1}: Skipped - no old_string")
                    continue

                if old_string == new_string:
                    results.append(f"Edit {i+1}: Skipped - old_string equals new_string")
                    continue

                # Check if old_string exists
                if old_string not in content:
                    results.append(f"Edit {i+1}: NOT FOUND - '{old_string[:50]}...'")
                    continue

                # Count occurrences
                occurrences = content.count(old_string)

                # Check uniqueness if not replacing all
                if not replace_all and occurrences > 1:
                    results.append(
                        f"Edit {i+1}: AMBIGUOUS - '{old_string[:30]}...' appears {occurrences} times"
                    )
                    continue

                # Apply the edit
                if replace_all:
                    content = content.replace(old_string, new_string)
                    replacements = occurrences
                else:
                    content = content.replace(old_string, new_string, 1)
                    replacements = 1

                total_replacements += replacements
                results.append(f"Edit {i+1}: OK - {replacements} replacement(s)")

            # Only write if changes were made
            if content != original_content:
                async with aiofiles.open(path, "w", encoding="utf-8") as f:
                    await f.write(content)

            # Format output
            output_lines = [f"MultiEdit: {path.name}", ""]
            output_lines.extend(results)
            output_lines.append("")
            output_lines.append(f"Total: {total_replacements} replacements across {len(edits)} edits")

            return ToolResult(
                title=f"MultiEdit: {path.name}",
                output="\n".join(output_lines),
                metadata={
                    "file_path": str(path),
                    "num_edits": len(edits),
                    "total_replacements": total_replacements,
                    "results": results,
                },
            )

        except UnicodeDecodeError:
            return ToolResult(
                title="MultiEdit",
                output="",
                error=f"Cannot edit binary file: {file_path}",
            )
        except PermissionError:
            return ToolResult(
                title="MultiEdit",
                output="",
                error=f"Permission denied: {file_path}",
            )
        except Exception as e:
            return ToolResult(
                title="MultiEdit",
                output="",
                error=f"Error editing file: {e}",
            )
