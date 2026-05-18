"""
Per-turn skill selection for the session processor.

Thin wrapper around the existing ``coder.skills`` BM25 matcher that:

- Caches the BM25 index keyed on the skills file mtime so subsequent turns
  pay only the scoring cost, not the reindex cost.
- Skips the remote LLM curation path (``curate_embeds=False``) so selection
  stays inline and deterministic per turn.
- Returns lightweight skill records ready for prompt injection.

The heavy lifting (schema, BM25 setup, scoring) lives in
``coder.skills.find_best_skills_based_on_user_string_request1`` and is
reused verbatim — this module is a focused call-site adapter.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np

from oats.log import cl

try:
    from oats.skills.find_best_skills_based_on_user_string_request1 import (
        _resolve_skills_path,
        build_bm25_index,
        enhance_user_input,
        get_skill_descriptions,
        load_skills_menu,
    )
except ImportError:
    _resolve_skills_path = None  # type: ignore
    build_bm25_index = None  # type: ignore
    enhance_user_input = None  # type: ignore
    get_skill_descriptions = None  # type: ignore
    load_skills_menu = None  # type: ignore

log = cl("coder.skill_selector")

# Below this BM25 score the top match is noise — don't inject.
_MIN_SCORE = float(os.getenv("CODER_SKILL_MIN_SCORE", "1.0"))


@dataclass(frozen=True)
class SkillMatch:
    """A matched skill from the BM25 index.

    Attributes:
        name: The skill's display name.
        command: The slash command to invoke the skill.
        summary: Short summary of what the skill does.
        prompt: The skill's procedural prompt text.
        score: BM25 relevance score.
    """
    name: str
    command: str
    summary: str
    prompt: str
    score: float


class _IndexCache:
    """mtime-keyed cache of the BM25 index and skill records.

    Avoids re-indexing on every turn by checking the skills file mtime.
    When the file changes, the cache is invalidated and rebuilt.
    """

    def __init__(self) -> None:
        """Initialize an empty index cache."""
        self._path: str | None = None
        self._mtime: float | None = None
        self._desc_index = None
        self._skill_records: list[dict[str, Any]] = []
        self._skill_descriptions: list[str] = []

    def _current(self) -> tuple[str, float | None]:
        """Get the current skills file path and its mtime.

        Returns:
            Tuple of (file_path, mtime). mtime is None if the file doesn't exist.
        """
        path = _resolve_skills_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        return path, mtime

    def load(self) -> tuple[Any, list[str], list[dict[str, Any]]]:
        """Load or return the cached BM25 index.

        Returns the cached index if the skills file hasn't changed,
        otherwise rebuilds from disk.

        Returns:
            Tuple of (bm25_index, descriptions, skill_records).
        """
        path, mtime = self._current()
        if self._desc_index is not None and path == self._path and mtime == self._mtime:
            return self._desc_index, self._skill_descriptions, self._skill_records

        menu = load_skills_menu(refresh=True)
        _, descriptions, records, _, _ = get_skill_descriptions(menu)
        if not descriptions:
            log.warn(f"skills_index_empty path={path}")
            self._desc_index = None
            self._skill_descriptions = []
            self._skill_records = []
            self._path, self._mtime = path, mtime
            return None, [], []

        self._desc_index = build_bm25_index(descriptions)
        self._skill_descriptions = descriptions
        self._skill_records = records
        self._path, self._mtime = path, mtime
        log.info(f"skills_index_loaded path={path} count={len(records)}")
        return self._desc_index, descriptions, records


_cache = _IndexCache()


def select_skills_for_prompt(user_input: str, top_k: int = 1) -> list[SkillMatch]:
    """Return up to ``top_k`` skills matching the user prompt, best first.

    Uses pure BM25 against skill summaries; no remote LLM call. Scores below
    ``CODER_SKILL_MIN_SCORE`` are filtered out so the injection is skipped
    when nothing relevant is in the catalog.

    Args:
        user_input: The user's prompt text to match against.
        top_k: Maximum number of skills to return.

    Returns:
        List of SkillMatch objects, sorted by descending BM25 score.
    """
    if not user_input.strip():
        return []

    index, _descriptions, records = _cache.load()
    if index is None or not records:
        return []

    query_tokens = enhance_user_input(user_input).split()
    if not query_tokens:
        return []

    scores = np.array(index.get_scores(query_tokens))
    if scores.size == 0:
        return []

    ranked = np.argsort(scores)[::-1][:top_k]
    matches: list[SkillMatch] = []
    for idx in ranked:
        score = float(scores[idx])
        if score < _MIN_SCORE:
            continue
        rec = records[int(idx)]
        matches.append(
            SkillMatch(
                name=rec.get("skill_name", ""),
                command=rec.get("skill_cmd", ""),
                summary=rec.get("skill_summary", "")[:500],
                prompt=(rec.get("skill_prompt") or "").strip(),
                score=round(score, 3),
            )
        )
    return matches


def format_skill_section(matches: list[SkillMatch]) -> str | None:
    """Format matched skills as a system-prompt section. Returns None if empty.

    Keeps the section compact: one heading per skill with name, command, and
    the skill's own procedural prompt inlined.

    Args:
        matches: List of SkillMatch objects to format.

    Returns:
        Markdown-formatted string, or None if no matches.
    """
    if not matches:
        return None
    lines: list[str] = ["# Relevant Skills", ""]
    for m in matches:
        lines.append(f"## {m.name}  `/{m.command}`  (score {m.score})")
        if m.summary:
            lines.append(m.summary)
        if m.prompt:
            lines.append("")
            lines.append(m.prompt)
        lines.append("")
    return "\n".join(lines).rstrip()


def reset_cache() -> None:
    """Testing hook — drop the cached BM25 index and create a fresh cache."""
    global _cache
    _cache = _IndexCache()
