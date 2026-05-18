"""
Tool ranking index with inertia tracking.

Maintains a ranking of tools based on:
1. BM25 relevance (keyword match against tool descriptions)
2. Tool inertia (sequential usage patterns from AutoTool paper)
3. Reliability (success rate with Bayesian smoothing)
4. Latency (inverse normalized response time)

The ranking is persisted as an MD file for transparency and debugging.

References:

- AutoTool: Efficient Tool Selection for LLM Agents (2024)
  CIPS = (1-alpha) * Scorefreq + alpha * Scorectx

- Gorilla: LLM Connected with Massive APIs (NeurIPS 2024)
"""
from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Any

from oats.log import cl
from oats.mcp.models import (
    MCPToolDefinition,
    RankingIndex,
    ToolCallRecord,
    ToolCallStatus,
    ToolRankEntry,
)

log = cl("mcp.ranking")

# Weights for composite scoring
RELEVANCE_WEIGHT = 0.30
RELIABILITY_WEIGHT = 0.25
LATENCY_WEIGHT = 0.15
INERTIA_WEIGHT = 0.30

# Cap inertial predictions at 30% per AutoTool paper recommendation
INERTIA_CAP = 0.30
# Confidence threshold: only use inertia above this score
INERTIA_THRESHOLD = 0.1


class ToolRanker:
    """
    Builds and maintains a ranking index over registered MCP tools.

    Scoring dimensions:
    1. Relevance: BM25-style text matching against tool name/description/tags
    2. Inertia: What tool typically follows the last-used tool (sequential patterns)
    3. Reliability: Success rate weighted by recency
    4. Latency: Inverse normalized average response time
    """

    def __init__(self) -> None:
        """Initialize the ranker with empty index, stats, and inertia graph."""
        self._index = RankingIndex()
        self._tool_stats: dict[str, _ToolStats] = {}
        # Tool inertia graph: prev_tool -> {next_tool -> count}
        self._inertia_graph: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._last_tool: str | None = None
        self._total_transitions: int = 0
        # BM25 parameters
        self._k1 = 1.5
        self._b = 0.75

    def build_index(self, tools: list[MCPToolDefinition]) -> RankingIndex:
        """Build the ranking index from a list of tool definitions."""
        self._index = RankingIndex()

        for tool in tools:
            stats = self._tool_stats.get(tool.name, _ToolStats())
            entry = ToolRankEntry(
                tool_name=tool.name,
                server_name=tool.server_name,
                relevance_score=0.0,
                reliability_score=stats.reliability_score,
                latency_score=stats.latency_score,
                inertia_score=0.0,
                score=stats.composite_score,
                tags=tool.tags,
            )
            self._index.entries.append(entry)

        self._index.last_updated = time.time()
        return self._index

    def rank_for_query(
        self,
        query: str,
        tools: list[MCPToolDefinition],
        top_k: int = 20,
    ) -> list[ToolRankEntry]:
        """
        Rank tools for a specific query/task description.

        Combines BM25 relevance, tool inertia, reliability, and latency.
        """
        # Build document corpus for BM25
        documents: list[list[str]] = []
        for tool in tools:
            doc = f"{tool.name} {tool.description} {' '.join(tool.tags)}"
            documents.append(doc.lower().split())

        query_terms = query.lower().split()
        avg_dl = sum(len(d) for d in documents) / max(len(documents), 1)

        # Compute IDF for query terms
        idf: dict[str, float] = {}
        n = len(documents)
        for term in query_terms:
            df = sum(1 for doc in documents if term in doc)
            idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1)

        entries: list[ToolRankEntry] = []
        for i, tool in enumerate(tools):
            doc = documents[i]
            dl = len(doc)

            # BM25 relevance
            bm25_score = 0.0
            for term in query_terms:
                tf = doc.count(term)
                numerator = tf * (self._k1 + 1)
                denominator = tf + self._k1 * (1 - self._b + self._b * dl / max(avg_dl, 1))
                bm25_score += idf.get(term, 0) * (numerator / max(denominator, 0.001))

            relevance = min(bm25_score / max(len(query_terms), 1), 1.0)

            # Tool inertia score
            inertia = self._compute_inertia(tool.name)

            stats = self._tool_stats.get(tool.name, _ToolStats())

            composite = (
                RELEVANCE_WEIGHT * relevance
                + RELIABILITY_WEIGHT * stats.reliability_score
                + LATENCY_WEIGHT * stats.latency_score
                + INERTIA_WEIGHT * min(inertia, INERTIA_CAP)
            )

            entries.append(
                ToolRankEntry(
                    tool_name=tool.name,
                    server_name=tool.server_name,
                    score=composite,
                    relevance_score=relevance,
                    reliability_score=stats.reliability_score,
                    latency_score=stats.latency_score,
                    inertia_score=inertia,
                    tags=tool.tags,
                )
            )

        entries.sort(key=lambda e: e.score, reverse=True)
        return entries[:top_k]

    def record_call(self, record: ToolCallRecord) -> None:
        """Update stats and inertia graph from a completed tool call."""
        if record.tool_name not in self._tool_stats:
            self._tool_stats[record.tool_name] = _ToolStats()

        stats = self._tool_stats[record.tool_name]
        stats.total_calls += 1

        if record.status in (ToolCallStatus.SUCCESS, ToolCallStatus.RESOLVED):
            stats.successes += 1
        elif record.status == ToolCallStatus.ERROR:
            stats.failures += 1

        if record.latency_ms is not None:
            stats.total_latency_ms += record.latency_ms
            stats.latency_count += 1

        stats.last_used = time.time()
        stats.recompute()

        # Update inertia graph: record transition from last tool to this one
        if self._last_tool and self._last_tool != record.tool_name:
            self._inertia_graph[self._last_tool][record.tool_name] += 1
            self._total_transitions += 1
        self._last_tool = record.tool_name

    def _compute_inertia(self, tool_name: str) -> float:
        """
        Compute inertia score: how likely is this tool to follow the last-used tool?

        Based on AutoTool paper's Tool Inertia Graph (TIG).
        Returns 0.0 if no history or below confidence threshold.
        """
        if not self._last_tool or self._last_tool not in self._inertia_graph:
            return 0.0

        transitions = self._inertia_graph[self._last_tool]
        total_from_last = sum(transitions.values())
        if total_from_last == 0:
            return 0.0

        freq = transitions.get(tool_name, 0) / total_from_last

        # Below confidence threshold — fall back to other signals
        if freq < INERTIA_THRESHOLD:
            return 0.0

        return freq

    @property
    def index(self) -> RankingIndex:
        """Return the current ranking index."""
        return self._index


class _ToolStats:
    """Internal statistics tracker for a tool."""

    def __init__(self) -> None:
        """Initialize with zeroed counters and default 0.5 scores."""
        self.total_calls: int = 0
        self.successes: int = 0
        self.failures: int = 0
        self.total_latency_ms: float = 0.0
        self.latency_count: int = 0
        self.last_used: float = 0.0
        self.reliability_score: float = 0.5
        self.latency_score: float = 0.5
        self.composite_score: float = 0.5

    def recompute(self) -> None:
        """Recompute scores from raw stats."""
        # Reliability: success rate with Bayesian smoothing (prior=2 successes, 4 total)
        self.reliability_score = (self.successes + 2) / (self.total_calls + 4)

        # Latency: inverse normalized (lower latency = higher score)
        if self.latency_count > 0:
            avg_ms = self.total_latency_ms / self.latency_count
            self.latency_score = 1.0 / (1.0 + avg_ms / 1000.0)
        else:
            self.latency_score = 0.5

        self.composite_score = (
            RELIABILITY_WEIGHT * self.reliability_score
            + LATENCY_WEIGHT * self.latency_score
        )
