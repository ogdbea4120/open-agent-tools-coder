"""
Grep tool for searching file contents with regex patterns.

Provides :class:`GrepTool` which searches for patterns in files using
ripgrep (if available) or Python regex as a fallback. Supports file type
filtering, context lines, and multiple output modes.
"""
from __future__ import annotations


import asyncio
import re
import shutil
from pathlib import Path
from typing import Any
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.grep')


class GrepTool(Tool):
    """Search for regex patterns in file contents.

    Uses ripgrep if available, otherwise falls back to Python regex.
    Supports file type filtering, context lines, and multiple output
    modes (content, files, count).

    Example:
        ::

            grep pattern="def .*\\(self" path="src/"
            grep pattern="TODO" glob="*.py" output_mode="files"
    """

    MAX_RESULTS = 200
    MAX_CONTEXT_LINES = 5

    def is_concurrency_safe(self, args: dict[str, Any] | None = None) -> bool:
        return True

    @property
    def name(self) -> str:
        return "grep"

    @property
    def aliases(self) -> list[str]:
        return ["search", "search_code", "ripgrep"]

    @property
    def keywords(self) -> list[str]:
        return [
            "search text",
            "find string",
            "find references",
            "search codebase",
            "regex search",
        ]

    @property
    def always_load(self) -> bool:
        return True

    @property
    def strict(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return """Search for patterns in files using regex.

Uses ripgrep if available, falls back to Python regex.

Supports:
- Regular expressions
- File type filtering (--type py)
- Context lines (-A, -B, -C)
- Case insensitive search (-i)"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search (defaults to project root)",
                },
                "glob": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '*.py')",
                },
                "type": {
                    "type": "string",
                    "description": "File type to search (e.g., 'py', 'js', 'ts')",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case insensitive search",
                    "default": False,
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines to show",
                    "default": 0,
                },
                "output_mode": {
                    "type": "string",
                    "description": "Output mode: 'content' (show matches), 'files' (file paths only), 'count'",
                    "enum": ["content", "files", "count"],
                    "default": "files",
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
        """Search for regex patterns in files.

        Uses ripgrep if available, otherwise falls back to Python regex.
        Supports file type filtering, context lines, and multiple output modes.

        Args:
            args: Must contain ``pattern`` (str). May contain ``path`` (str),
                ``glob`` (str), ``type`` (str), ``case_insensitive`` (bool),
                ``context_lines`` (int), and ``output_mode`` (str: 'content', 'files', 'count').
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with search results or an error message.
        """
        pattern = args.get("pattern", "")
        search_path = args.get("path")
        glob_pattern = args.get("glob")
        file_type = args.get("type")
        case_insensitive = args.get("case_insensitive", False)
        context_lines = min(args.get("context_lines", 0), self.MAX_CONTEXT_LINES)
        output_mode = args.get("output_mode", "files")

        if not pattern:
            return ToolResult(
                title="Grep",
                output="",
                error="No pattern provided",
            )

        base_path = self._resolve_path(search_path, ctx)

        # Try ripgrep first
        if shutil.which("rg"):
            return await self._ripgrep_search(
                pattern=pattern,
                base_path=base_path,
                glob_pattern=glob_pattern,
                file_type=file_type,
                case_insensitive=case_insensitive,
                context_lines=context_lines,
                output_mode=output_mode,
            )
        else:
            return await self._python_search(
                pattern=pattern,
                base_path=base_path,
                glob_pattern=glob_pattern,
                file_type=file_type,
                case_insensitive=case_insensitive,
                output_mode=output_mode,
            )

    async def _ripgrep_search(
        self,
        pattern: str,
        base_path: Path,
        glob_pattern: str | None,
        file_type: str | None,
        case_insensitive: bool,
        context_lines: int,
        output_mode: str,
    ) -> ToolResult:
        """Search files using the ripgrep (``rg``) binary.

        Builds the ``rg`` command with the appropriate flags for case sensitivity,
        output mode (files/count/content), glob filters, and file type filters.
        Results are truncated to MAX_RESULTS.

        Args:
            pattern: The regex pattern to search for.
            base_path: The directory to search in.
            glob_pattern: Optional glob pattern to filter files.
            file_type: Optional file type to filter by (e.g. ``py``, ``js``).
            case_insensitive: Whether to search case-insensitively.
            context_lines: Number of context lines to include.
            output_mode: One of ``files``, ``count``, or ``content``.

        Returns:
            A :class:`ToolResult` with the search results.
        """
        cmd = ["rg", "--color=never", "--no-heading"]

        if case_insensitive:
            cmd.append("-i")

        if output_mode == "files":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")
        else:  # content
            cmd.append("-n")
            if context_lines > 0:
                cmd.extend(["-C", str(context_lines)])

        if glob_pattern:
            cmd.extend(["--glob", glob_pattern])

        if file_type:
            cmd.extend(["--type", file_type])

        cmd.append(pattern)
        cmd.append(str(base_path))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=60,
            )

            output = stdout.decode("utf-8", errors="replace")

            # Count results
            lines = [l for l in output.strip().split("\n") if l]
            total_results = len(lines)
            truncated = False

            if total_results > self.MAX_RESULTS:
                lines = lines[: self.MAX_RESULTS]
                output = "\n".join(lines)
                output += f"\n\n[Showing {self.MAX_RESULTS} of {total_results} matches]"
                truncated = True

            if not output.strip():
                output = f"No matches for '{pattern}'"

            return ToolResult(
                title=f"Grep: {pattern}",
                output=output,
                metadata={
                    "pattern": pattern,
                    "base_path": str(base_path),
                    "total_matches": total_results,
                    "truncated": truncated,
                    "tool": "ripgrep",
                },
            )

        except asyncio.TimeoutError:
            return ToolResult(
                title="Grep",
                output="",
                error="Search timed out",
            )
        except Exception as e:
            return ToolResult(
                title="Grep",
                output="",
                error=f"Search error: {e}",
            )

    async def _python_search(
        self,
        pattern: str,
        base_path: Path,
        glob_pattern: str | None,
        file_type: str | None,
        case_insensitive: bool,
        output_mode: str,
    ) -> ToolResult:
        """Fallback search using Python's ``re`` module when ripgrep is unavailable.

        Walks the directory tree, applies glob and file type filters, and searches
        each file's contents with the compiled regex pattern. Results are truncated
        to MAX_RESULTS.

        Args:
            pattern: The regex pattern to search for.
            base_path: The directory to search in.
            glob_pattern: Optional glob pattern to filter files.
            file_type: Optional file type to filter by (e.g. ``py``, ``js``).
            case_insensitive: Whether to search case-insensitively.
            output_mode: One of ``files``, ``count``, or ``content``.

        Returns:
            A :class:`ToolResult` with the search results.
        """
        try:
            flags = re.IGNORECASE if case_insensitive else 0
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(
                title="Grep",
                output="",
                error=f"Invalid regex: {e}",
            )

        # Determine files to search
        if base_path.is_file():
            files = [base_path]
        else:
            if glob_pattern:
                files = list(base_path.rglob(glob_pattern))
            elif file_type:
                ext_map = {
                    "py": "*.py",
                    "js": "*.js",
                    "ts": "*.ts",
                    "tsx": "*.tsx",
                    "jsx": "*.jsx",
                    "java": "*.java",
                    "go": "*.go",
                    "rs": "*.rs",
                    "cpp": "*.cpp",
                    "c": "*.c",
                    "h": "*.h",
                }
                glob_pat = ext_map.get(file_type, f"*.{file_type}")
                files = list(base_path.rglob(glob_pat))
            else:
                files = list(base_path.rglob("*"))

        files = [f for f in files if f.is_file()]

        results: list[str] = []
        match_count = 0

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                matches = list(regex.finditer(content))

                if matches:
                    match_count += len(matches)
                    rel_path = str(file_path.relative_to(base_path))

                    if output_mode == "files":
                        results.append(rel_path)
                    elif output_mode == "count":
                        results.append(f"{rel_path}:{len(matches)}")
                    else:  # content
                        lines = content.split("\n")
                        for match in matches:
                            line_num = content[: match.start()].count("\n") + 1
                            if line_num <= len(lines):
                                line = lines[line_num - 1]
                                results.append(f"{rel_path}:{line_num}:{line}")

            except Exception:
                continue

            if len(results) >= self.MAX_RESULTS:
                break

        truncated = len(results) >= self.MAX_RESULTS

        if not results:
            output = f"No matches for '{pattern}'"
        else:
            output = "\n".join(results)
            if truncated:
                output += f"\n\n[Results truncated at {self.MAX_RESULTS}]"

        return ToolResult(
            title=f"Grep: {pattern}",
            output=output,
            metadata={
                "pattern": pattern,
                "base_path": str(base_path),
                "total_matches": match_count,
                "truncated": truncated,
                "tool": "python",
            },
        )
