"""
Edit tool for modifying existing files.

Provides :class:`EditTool` which edits files by replacing text with smart
fallback strategies for models that struggle with exact string matching:

1. **Exact match** (primary path) — direct string replacement
2. **Fuzzy match** — find closest matching block in the file (>80% confidence)
3. **Write-swap** — rebuild the entire file with the intended change applied

Helper functions:

- :func:`_fuzzy_find_best_match` — Find the best fuzzy match for a target string.
- :func:`_apply_write_swap` — Last-resort strategy to rebuild the file.
"""
from __future__ import annotations

import difflib
import logging

import aiofiles
from pathlib import Path
from typing import Any

from oats.core.features import lsp_tools_candidate_enabled
from oats.lsp.client import sync_file_and_collect_diagnostics
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.edit')


def _fuzzy_find_best_match(
    content: str,
    old_string: str,
    threshold: float = 0.80,
) -> tuple[str, float] | None:
    """Find the substring in *content* that best matches *old_string*.

    Slides a window over the file lines whose height equals the number of
    lines in ``old_string`` (+/- 2 lines tolerance) and scores each candidate
    with ``SequenceMatcher``.

    Args:
        content: The full file content.
        old_string: The target string to match against.
        threshold: Minimum similarity ratio to accept (default 0.80).

    Returns:
        ``(best_candidate, ratio)`` if a match exceeds the threshold,
        otherwise ``None``.
    """
    old_lines = old_string.splitlines(keepends=True)
    content_lines = content.splitlines(keepends=True)
    target_len = len(old_lines)

    if target_len == 0 or len(content_lines) == 0:
        return None

    best: tuple[str, float] | None = None
    best_ratio = threshold  # only accept matches above threshold

    # Try window sizes from (target_len - 2) to (target_len + 2)
    lo = max(1, target_len - 2)
    hi = min(len(content_lines), target_len + 2)

    for window_size in range(lo, hi + 1):
        for start in range(len(content_lines) - window_size + 1):
            candidate_lines = content_lines[start : start + window_size]
            candidate = "".join(candidate_lines)
            ratio = difflib.SequenceMatcher(
                None, old_string, candidate, autojunk=False
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = (candidate, ratio)

    return best


def _apply_write_swap(content: str, old_string: str, new_string: str) -> str | None:
    """Last-resort strategy: rebuild the file with the intended change applied.

    Finds the block of lines in *content* whose collective similarity to
    ``old_string`` is highest (no threshold — picks the best available) and
    replaces that block with ``new_string``.

    Args:
        content: The full file content.
        old_string: The intended old text (may not match exactly).
        new_string: The replacement text.

    Returns:
        The new file content, or ``None`` if no plausible location is found
        (similarity below 50%).
    """
    old_lines = old_string.splitlines(keepends=True)
    content_lines = content.splitlines(keepends=True)
    target_len = len(old_lines)

    if target_len == 0 or len(content_lines) == 0:
        return None

    best_start = 0
    best_end = 0
    best_ratio = 0.0

    lo = max(1, target_len - 3)
    hi = min(len(content_lines), target_len + 3)

    for window_size in range(lo, hi + 1):
        for start in range(len(content_lines) - window_size + 1):
            candidate = "".join(content_lines[start : start + window_size])
            ratio = difflib.SequenceMatcher(
                None, old_string, candidate, autojunk=False
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = start
                best_end = start + window_size

    # Require at least 50% similarity for write-swap to proceed
    if best_ratio < 0.50:
        return None

    # Rebuild the file with the replacement spliced in
    new_lines = new_string.splitlines(keepends=True)
    # Ensure new_string ends with newline if original block did
    if new_lines and not new_string.endswith("\n") and (
        best_end <= len(content_lines)
        and content_lines[best_end - 1].endswith("\n")
    ):
        new_lines[-1] = new_lines[-1] + "\n"

    result_lines = content_lines[:best_start] + new_lines + content_lines[best_end:]
    return "".join(result_lines)


class EditTool(Tool):
    """Edit files by replacing exact text with fallback strategies.

    Primary strategy is exact string matching. If that fails, two fallback
    strategies are tried:

    1. **Fuzzy match** — finds the closest matching block (>80% similarity)
    2. **Write-swap** — rebuilds the file with the best available replacement

    This makes the tool robust against minor indentation or whitespace
    differences that can occur when LLMs generate ``old_string`` values.

    Example:
        ::

            edit file_path="src/main.py" old_string="def old():" new_string="def new():"
    """

    @property
    def name(self) -> str:
        return "edit"

    @property
    def aliases(self) -> list[str]:
        return ["replace_in_file", "file_edit"]

    @property
    def keywords(self) -> list[str]:
        return [
            "edit file",
            "replace text",
            "modify existing file",
            "update code block",
        ]

    @property
    def strict(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return """Edit a file by replacing text.

Performs exact string replacement. The old_string must match exactly
(including whitespace and indentation).

Use replace_all=true to replace all occurrences."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find and replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "The text to replace it with",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false)",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    def requires_permission(self, args: dict[str, Any], ctx: ToolContext) -> str | None:
        """Edit operations always require user permission.

        Args:
            args: The tool arguments containing the ``file_path``.
            ctx: The tool execution context.

        Returns:
            A permission prompt string describing the file to be edited.
        """
        file_path = args.get("file_path", "")
        return f"Edit file: {file_path}"

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
        """Edit a file by replacing text, with smart fallback strategies.

        Tries three strategies in order:
        1. **Exact match** — direct string replacement.
        2. **Fuzzy match** — find the closest matching block (>80% similarity).
        3. **Write-swap** — rebuild the file with the intended change applied.

        Args:
            args: Must contain ``file_path`` (str), ``old_string`` (str),
                ``new_string`` (str). May contain ``replace_all`` (bool).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the edit result and strategy used.
        """
        file_path = args.get("file_path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        replace_all = args.get("replace_all", False)

        if not file_path:
            return ToolResult(
                title="Edit",
                output="",
                error="No file path provided",
            )

        if not old_string:
            return ToolResult(
                title="Edit",
                output="",
                error="No old_string provided",
            )

        if old_string == new_string:
            return ToolResult(
                title="Edit",
                output="",
                error="old_string and new_string are identical",
            )

        try:
            path = self._resolve_path(file_path, ctx)

            if not path.exists():
                return ToolResult(
                    title="Edit",
                    output="",
                    error=f"File not found: {path}",
                )

            # Read the file
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                content = await f.read()

            # ----------------------------------------------------------
            # Strategy 1: Exact match (primary path)
            # ----------------------------------------------------------
            if old_string in content:
                return await self._apply_exact(
                    path, content, old_string, new_string, replace_all, ctx
                )

            # ----------------------------------------------------------
            # Strategy 2: Fuzzy match (>80% similarity)
            # ----------------------------------------------------------
            log.info(
                "[smart-edit] Exact match failed for %s – attempting fuzzy match",
                path.name,
            )
            fuzzy = _fuzzy_find_best_match(content, old_string, threshold=0.80)
            if fuzzy is not None:
                matched_text, ratio = fuzzy
                pct = f"{ratio * 100:.1f}%"
                log.info(
                    "[smart-edit] Fuzzy match found in %s (confidence %s)",
                    path.name,
                    pct,
                )
                # Replace the fuzzy-matched text with new_string
                new_content = content.replace(matched_text, new_string, 1)

                async with aiofiles.open(path, "w", encoding="utf-8") as f:
                    await f.write(new_content)

                if ctx.file_cache:
                    ctx.file_cache.mark_written(str(path))
                lsp_synced = False
                lsp_diagnostics = None
                if lsp_tools_candidate_enabled():
                    try:
                        lsp_synced, lsp_diagnostics = await sync_file_and_collect_diagnostics(
                            ctx.project_dir, path, new_content
                        )
                    except Exception:
                        lsp_synced = False
                        lsp_diagnostics = None

                strategy_note = (
                    f"[smart-edit] Used FUZZY MATCH strategy (confidence {pct}). "
                    f"Matched text differed from old_string but was close enough to apply."
                )
                output = (
                    f"Replaced 1 occurrence in {path.name} via fuzzy match ({pct} confidence).\n"
                    f"{strategy_note}"
                )
                if lsp_diagnostics:
                    output = f"{output}\n\n{lsp_diagnostics}"
                return ToolResult(
                    title=f"Edit (fuzzy): {path.name}",
                    output=output,
                    metadata={
                        "file_path": str(path),
                        "replacements": 1,
                        "strategy": "fuzzy_match",
                        "fuzzy_confidence": ratio,
                        "old_string_length": len(old_string),
                        "new_string_length": len(new_string),
                        "lsp_synced": lsp_synced,
                        "lsp_diagnostics": lsp_diagnostics,
                    },
                )

            # ----------------------------------------------------------
            # Strategy 3: Write-swap (rebuild file with change spliced in)
            # ----------------------------------------------------------
            log.info(
                "[smart-edit] Fuzzy match failed for %s – attempting write-swap",
                path.name,
            )
            swapped = _apply_write_swap(content, old_string, new_string)
            if swapped is not None:
                async with aiofiles.open(path, "w", encoding="utf-8") as f:
                    await f.write(swapped)

                if ctx.file_cache:
                    ctx.file_cache.mark_written(str(path))
                lsp_synced = False
                lsp_diagnostics = None
                if lsp_tools_candidate_enabled():
                    try:
                        lsp_synced, lsp_diagnostics = await sync_file_and_collect_diagnostics(
                            ctx.project_dir, path, swapped
                        )
                    except Exception:
                        lsp_synced = False
                        lsp_diagnostics = None

                strategy_note = (
                    "[smart-edit] Used WRITE-SWAP strategy. "
                    "Could not find an exact or high-confidence fuzzy match, "
                    "so the file was rewritten with the best-guess replacement applied."
                )
                output = f"Applied edit to {path.name} via write-swap strategy.\n{strategy_note}"
                if lsp_diagnostics:
                    output = f"{output}\n\n{lsp_diagnostics}"
                return ToolResult(
                    title=f"Edit (write-swap): {path.name}",
                    output=output,
                    metadata={
                        "file_path": str(path),
                        "replacements": 1,
                        "strategy": "write_swap",
                        "old_string_length": len(old_string),
                        "new_string_length": len(new_string),
                        "lsp_synced": lsp_synced,
                        "lsp_diagnostics": lsp_diagnostics,
                    },
                )

            # ----------------------------------------------------------
            # All strategies exhausted
            # ----------------------------------------------------------
            return ToolResult(
                title="Edit",
                output="",
                error=(
                    f"old_string not found in {path.name}. "
                    "All smart-edit strategies (exact, fuzzy, write-swap) failed. "
                    "Ensure the string matches the file content."
                ),
            )

        except UnicodeDecodeError:
            return ToolResult(
                title="Edit",
                output="",
                error=f"Cannot edit binary file: {file_path}",
            )
        except PermissionError:
            return ToolResult(
                title="Edit",
                output="",
                error=f"Permission denied: {file_path}",
            )
        except Exception as e:
            return ToolResult(
                title="Edit",
                output="",
                error=f"Error editing file: {e}",
            )

    async def _apply_exact(
        self,
        path: Path,
        content: str,
        old_string: str,
        new_string: str,
        replace_all: bool,
        ctx: ToolContext,
    ) -> ToolResult:
        """Apply an exact string replacement and write the file.

        Args:
            path: The resolved file path.
            content: The current file content.
            old_string: The text to find.
            new_string: The replacement text.
            replace_all: Whether to replace all occurrences.
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the edit result.
        """
        occurrences = content.count(old_string)

        if not replace_all and occurrences > 1:
            return ToolResult(
                title="Edit",
                output="",
                error=f"old_string appears {occurrences} times in {path.name}. "
                "Use replace_all=true to replace all, or provide more context to make it unique.",
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = occurrences
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(new_content)

        if ctx.file_cache:
            ctx.file_cache.mark_written(str(path))
        lsp_synced = False
        lsp_diagnostics = None
        if lsp_tools_candidate_enabled():
            try:
                lsp_synced, lsp_diagnostics = await sync_file_and_collect_diagnostics(
                    ctx.project_dir, path, new_content
                )
            except Exception:
                lsp_synced = False
                lsp_diagnostics = None

        log.debug("[smart-edit] Exact match applied in %s", path.name)

        output = f"Replaced {replacements} occurrence{'s' if replacements > 1 else ''} in {path.name}"
        if lsp_diagnostics:
            output = f"{output}\n\n{lsp_diagnostics}"
        return ToolResult(
            title=f"Edit: {path.name}",
            output=output,
            metadata={
                "file_path": str(path),
                "replacements": replacements,
                "strategy": "exact_match",
                "old_string_length": len(old_string),
                "new_string_length": len(new_string),
                "lsp_synced": lsp_synced,
                "lsp_diagnostics": lsp_diagnostics,
            },
        )
