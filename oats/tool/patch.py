"""
ApplyPatch tool for applying unified diff patches.

Provides :class:`ApplyPatchTool` which applies standard unified diff format
patches (like output from ``git diff`` or ``diff -u``) to one or more files.

Data classes:

- :class:`PatchHunk` — A single hunk from a unified diff patch.
- :class:`FilePatch` — Patch metadata for a single file.
"""

from __future__ import annotations

import aiofiles
import re
from pathlib import Path
from typing import Any
from dataclasses import dataclass
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl("tool.multiedit")


@dataclass
class PatchHunk:
    """A single hunk from a unified diff patch.

    Attributes:
        old_start: Starting line number in the original file (1-based).
        old_count: Number of lines in the original file for this hunk.
        new_start: Starting line number in the new file (1-based).
        new_count: Number of lines in the new file for this hunk.
        lines: The hunk body lines (prefixed with ``+``, ``-``, or space).
    """

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


@dataclass
class FilePatch:
    """Patch metadata for a single file.

    Attributes:
        old_path: Path in the original file (from ``---`` line).
        new_path: Path in the new file (from ``+++`` line).
        hunks: List of :class:`PatchHunk` objects for this file.
        is_new: ``True`` if this is a new file (old path is ``/dev/null``).
        is_deleted: ``True`` if this is a deleted file (new path is ``/dev/null``).
    """

    old_path: str
    new_path: str
    hunks: list[PatchHunk]
    is_new: bool = False
    is_deleted: bool = False


class ApplyPatchTool(Tool):
    """Apply a unified diff patch to one or more files.

    Accepts standard unified diff format (like output from ``git diff``
    or ``diff -u``). Supports multi-file patches, new files, and deleted
    files. Hunks are applied in reverse order to maintain line number
    integrity.

    Example:

        Call ``apply_patch`` with a unified diff patch string as the ``patch`` argument.
    """

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def aliases(self) -> list[str]:
        return ["patch", "unified_diff"]

    @property
    def keywords(self) -> list[str]:
        return [
            "apply patch",
            "unified diff",
            "multi file edit",
            "complex code edit",
        ]

    @property
    def strict(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return """Apply a unified diff patch to one or more files.

Accepts standard unified diff format (like output from 'git diff' or 'diff -u').

Example patch format:
```
--- a/file.py
+++ b/file.py
@@ -10,5 +10,6 @@
 unchanged line
-removed line
+added line
 unchanged line
```

Use this for complex multi-line changes or when you have a patch to apply."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "The unified diff patch content",
                },
                "strip": {
                    "type": "integer",
                    "description": "Number of path components to strip (like patch -p, default 1)",
                    "default": 1,
                },
            },
            "required": ["patch"],
        }

    def requires_permission(self, args: dict[str, Any], ctx: ToolContext) -> str | None:
        """Patch operations always require user permission.

        Args:
            args: The tool arguments containing the ``patch`` content.
            ctx: The tool execution context.

        Returns:
            A permission prompt string describing the number of affected files.
        """
        patch = args.get("patch", "")
        # Count affected files
        files = re.findall(r"^(?:---|\+\+\+) [ab]/(.+)$", patch, re.MULTILINE)
        unique_files = set(files)
        return f"Apply patch affecting {len(unique_files)} file(s)"

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Apply a unified diff patch to one or more files.

        Parses the patch, then creates, modifies, or deletes files as specified.

        Args:
            args: Must contain ``patch`` (str, the unified diff content).
                May contain ``strip`` (int, path components to strip, default 1).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with per-file results and a summary.
        """
        patch_content = args.get("patch", "")
        strip = args.get("strip", 1)

        if not patch_content:
            return ToolResult(
                title="ApplyPatch",
                output="",
                error="No patch content provided",
            )

        try:
            # Parse the patch
            file_patches = self._parse_patch(patch_content, strip)

            if not file_patches:
                return ToolResult(
                    title="ApplyPatch",
                    output="",
                    error="No valid patches found in input",
                )

            results = []
            files_modified = 0
            files_created = 0
            files_deleted = 0

            for fp in file_patches:
                file_path = ctx.working_dir / fp.new_path

                if fp.is_deleted:
                    # Delete file
                    if file_path.exists():
                        file_path.unlink()
                        files_deleted += 1
                        results.append(f"Deleted: {fp.old_path}")
                    else:
                        results.append(f"Already deleted: {fp.old_path}")
                    continue

                if fp.is_new:
                    # Create new file
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    content = self._get_new_content(fp)
                    async with aiofiles.open(file_path, "w") as f:
                        await f.write(content)
                    files_created += 1
                    results.append(f"Created: {fp.new_path}")
                    continue

                # Apply patch to existing file
                if not file_path.exists():
                    results.append(f"FAILED: {fp.new_path} not found")
                    continue

                async with aiofiles.open(file_path, "r") as f:
                    original_lines = (await f.read()).splitlines(keepends=True)

                try:
                    new_lines = self._apply_hunks(original_lines, fp.hunks)
                    async with aiofiles.open(file_path, "w") as f:
                        await f.writelines(new_lines)
                    files_modified += 1
                    results.append(f"Modified: {fp.new_path} ({len(fp.hunks)} hunks)")
                except ValueError as e:
                    results.append(f"FAILED: {fp.new_path} - {e}")

            # Format output
            output_lines = ["Patch applied:", ""]
            output_lines.extend(results)
            output_lines.append("")
            output_lines.append(
                f"Summary: {files_modified} modified, {files_created} created, {files_deleted} deleted"
            )

            return ToolResult(
                title="ApplyPatch",
                output="\n".join(output_lines),
                metadata={
                    "files_modified": files_modified,
                    "files_created": files_created,
                    "files_deleted": files_deleted,
                    "results": results,
                },
            )

        except Exception as e:
            return ToolResult(
                title="ApplyPatch",
                output="",
                error=f"Failed to apply patch: {e}",
            )

    def _parse_patch(self, content: str, strip: int) -> list[FilePatch]:
        """Parse a unified diff string into a list of :class:`FilePatch` objects.

        Handles new files (``/dev/null`` as old path), deleted files
        (``/dev/null`` as new path), and standard modifications.

        Args:
            content: The unified diff text.
            strip: Number of leading path components to strip (like ``patch -pN``).

        Returns:
            A list of :class:`FilePatch` objects.
        """
        patches: list[FilePatch] = []
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Look for file header
            if line.startswith("--- "):
                old_path = self._strip_path(line[4:].split("\t")[0], strip)
                i += 1

                if i < len(lines) and lines[i].startswith("+++ "):
                    new_path = self._strip_path(lines[i][4:].split("\t")[0], strip)
                    i += 1

                    # Check for new/deleted files
                    is_new = old_path == "/dev/null"
                    is_deleted = new_path == "/dev/null"

                    if is_new:
                        old_path = new_path
                    if is_deleted:
                        new_path = old_path

                    # Parse hunks
                    hunks = []
                    while i < len(lines) and lines[i].startswith("@@"):
                        hunk, i = self._parse_hunk(lines, i)
                        if hunk:
                            hunks.append(hunk)

                    patches.append(
                        FilePatch(
                            old_path=old_path,
                            new_path=new_path,
                            hunks=hunks,
                            is_new=is_new,
                            is_deleted=is_deleted,
                        )
                    )
                    continue

            i += 1

        return patches

    def _strip_path(self, path: str, strip: int) -> str:
        """Strip leading path components from a file path.

        Removes ``a/`` or ``b/`` prefixes (from unified diff headers) and then
        strips the specified number of additional path components.

        Args:
            path: The file path from the diff header.
            strip: Number of path components to strip (like ``patch -pN``).

        Returns:
            The stripped file path.
        """
        # Remove a/ or b/ prefix
        if path.startswith(("a/", "b/")):
            path = path[2:]
        elif strip > 0:
            parts = path.split("/")
            path = "/".join(parts[strip:]) if len(parts) > strip else path
        return path

    def _parse_hunk(self, lines: list[str], start: int) -> tuple[PatchHunk | None, int]:
        """Parse a single hunk from the patch lines.

        Extracts the line range metadata (``@@ -old_start,old_count +new_start,new_count @@``)
        and the hunk body lines.

        Args:
            lines: The full list of patch lines.
            start: The index of the ``@@`` header line.

        Returns:
            A tuple of ``(PatchHunk, next_index)`` or ``(None, next_index)`` if parsing fails.
        """
        line = lines[start]

        # Parse @@ -old_start,old_count +new_start,new_count @@
        match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not match:
            return None, start + 1

        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) else 1

        hunk_lines = []
        i = start + 1

        while i < len(lines):
            line = lines[i]
            if line.startswith(("@@", "--- ", "+++ ", "diff ")):
                break
            if line.startswith((" ", "-", "+", "\\")):
                hunk_lines.append(line)
            elif line == "":
                # Empty line in context
                hunk_lines.append(" ")
            i += 1

        return (
            PatchHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=hunk_lines,
            ),
            i,
        )

    def _get_new_content(self, fp: FilePatch) -> str:
        """Extract the new file content from a patch's hunks.

        Collects all added (``+``) and context (`` ``) lines from the hunks,
        stripping the prefix character.

        Args:
            fp: The :class:`FilePatch` for a new file.

        Returns:
            The reconstructed file content as a string.
        """
        lines = []
        for hunk in fp.hunks:
            for line in hunk.lines:
                if line.startswith("+"):
                    lines.append(line[1:])
                elif line.startswith(" "):
                    lines.append(line[1:])
        return "\n".join(lines)

    def _apply_hunks(
        self, original_lines: list[str], hunks: list[PatchHunk]
    ) -> list[str]:
        """Apply hunks to the original file content in reverse order.

        Reverses the hunks so that line numbers remain valid as earlier
        hunks are applied. Added (``+``) and context (`` ``) lines are
        kept; removed (``-``) lines are dropped.

        Args:
            original_lines: The original file lines (with newlines).
            hunks: The list of :class:`PatchHunk` objects to apply.

        Returns:
            The modified file lines as a list of strings.
        """
        # Convert to list for easier manipulation
        result = list(original_lines)

        # Apply hunks in reverse order to maintain line numbers
        for hunk in reversed(hunks):
            start_idx = hunk.old_start - 1  # Convert to 0-indexed

            # Build new content for this hunk
            new_content = []
            for line in hunk.lines:
                if line.startswith("+"):
                    # Add new line
                    content = line[1:]
                    if not content.endswith("\n"):
                        content += "\n"
                    new_content.append(content)
                elif line.startswith(" "):
                    # Context line - keep original
                    content = line[1:]
                    if not content.endswith("\n"):
                        content += "\n"
                    new_content.append(content)
                # Lines starting with - are removed (not added to new_content)

            # Replace the old content with new content
            end_idx = start_idx + hunk.old_count
            result[start_idx:end_idx] = new_content

        return result
