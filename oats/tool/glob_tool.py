"""
Glob tool for finding files by pattern.

Provides :class:`GlobTool` which finds files matching glob patterns,
supporting both recursive (``**``) and non-recursive patterns. Results
are sorted by modification time (newest first).
"""
from __future__ import annotations


import fnmatch
from pathlib import Path
from typing import Any
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.glob')


class GlobTool(Tool):
    """Find files matching a glob pattern.

    Supports both recursive (``**``) and non-recursive patterns.
    Results are sorted by modification time (newest first) and
    truncated to MAX_RESULTS (500).

    Example:
        ::

            glob pattern="**/*.py"
            glob pattern="*.ts" path="src/"
    """

    MAX_RESULTS = 500

    def is_concurrency_safe(self, args: dict[str, Any] | None = None) -> bool:
        return True

    @property
    def name(self) -> str:
        return "glob"

    @property
    def aliases(self) -> list[str]:
        return ["find_files", "list_files"]

    @property
    def keywords(self) -> list[str]:
        return [
            "find files",
            "match file pattern",
            "list matching files",
            "recursive file search",
        ]

    @property
    def always_load(self) -> bool:
        return True

    @property
    def strict(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return """Find files matching a glob pattern.

Supports patterns like:
- "*.py" - all Python files in current directory
- "**/*.ts" - all TypeScript files recursively
- "coder/**/*.js" - all JS files under coder/

Results are sorted by modification time (newest first)."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (e.g., '**/*.py')",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (defaults to project root)",
                },
            },
            "required": ["pattern"],
        }

    def _resolve_path(self, file_path: str | None, ctx: ToolContext) -> Path:
        """Resolve a path relative to the tool context's working directory.

        Args:
            file_path: The file path (absolute or relative), or ``None``.
            ctx: The tool execution context.

        Returns:
            The resolved absolute :class:`pathlib.Path`, or the working
            directory if ``file_path`` is ``None``.
        """
        if file_path is None:
            return ctx.working_dir
        path = Path(file_path)
        if not path.is_absolute():
            path = ctx.working_dir / path
        return path.resolve()

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Find files matching a glob pattern.

        Supports both recursive (``**``) and non-recursive patterns. Results are
        sorted by modification time (newest first) and truncated to MAX_RESULTS.

        Args:
            args: Must contain ``pattern`` (str). May contain ``path`` (str,
                directory to search in).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the list of matching file paths.
        """
        pattern = args.get("pattern", "")
        search_path = args.get("path")

        if not pattern:
            return ToolResult(
                title="Glob",
                output="",
                error="No pattern provided",
            )

        try:
            base_path = self._resolve_path(search_path, ctx)

            if not base_path.exists():
                return ToolResult(
                    title="Glob",
                    output="",
                    error=f"Directory not found: {base_path}",
                )

            if not base_path.is_dir():
                return ToolResult(
                    title="Glob",
                    output="",
                    error=f"Not a directory: {base_path}",
                )

            # Find matching files
            matches: list[Path] = []

            if "**" in pattern:
                # Recursive glob
                matches = list(base_path.glob(pattern))
            else:
                # Non-recursive - check if pattern has directory components
                if "/" in pattern or "\\" in pattern:
                    matches = list(base_path.glob(pattern))
                else:
                    # Single directory level
                    matches = list(base_path.glob(pattern))

            # Filter to files only (not directories)
            matches = [m for m in matches if m.is_file()]

            # Sort by modification time (newest first)
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            # Limit results
            total_matches = len(matches)
            truncated = total_matches > self.MAX_RESULTS
            if truncated:
                matches = matches[: self.MAX_RESULTS]

            # Format output
            if not matches:
                return ToolResult(
                    title="Glob",
                    output=f"No files matching '{pattern}' in {base_path}",
                    metadata={
                        "pattern": pattern,
                        "base_path": str(base_path),
                        "total_matches": 0,
                    },
                )

            # Make paths relative to base_path for cleaner output
            relative_paths = []
            for match in matches:
                try:
                    rel = match.relative_to(base_path)
                    relative_paths.append(str(rel))
                except ValueError:
                    relative_paths.append(str(match))

            output = "\n".join(relative_paths)

            if truncated:
                output += f"\n\n[Showing {self.MAX_RESULTS} of {total_matches} matches]"

            return ToolResult(
                title=f"Glob: {pattern}",
                output=output,
                metadata={
                    "pattern": pattern,
                    "base_path": str(base_path),
                    "total_matches": total_matches,
                    "shown_matches": len(matches),
                    "truncated": truncated,
                },
            )

        except Exception as e:
            return ToolResult(
                title="Glob",
                output="",
                error=f"Error searching files: {e}",
            )
