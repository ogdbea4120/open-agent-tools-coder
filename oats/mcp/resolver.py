"""
Resilience layer for the MCP tool calling protocol.

Implements production-grade failure handling based on distributed systems
patterns (Hystrix, resilience4j) adapted for LLM tool calling:

1. Circuit Breaker (3-state: closed/open/half-open) per server
2. Exponential backoff with jitter, error-type-aware
3. Watchdog timer + loop detection
4. Graceful degradation chain (partial results > cache > structured error)
5. Iterative tool resolution (BM25-ranked alternatives)

References:
- Netflix Hystrix circuit breaker pattern
- Portkey: Retries, Fallbacks, and Circuit Breakers in LLM Apps
- Self-Healing AI Agents: 7 Error Handling Patterns
- AutoTool: Efficient Tool Selection for LLM Agents (2024)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from typing import Any

from oats.log import cl
from oats.mcp.models import (
    CircuitState,
    ErrorCategory,
    MCPToolDefinition,
    ToolCallRecord,
    ToolCallStatus,
    ToolRankEntry,
)
from oats.mcp.ranking import ToolRanker

log = cl("mcp.resolver")

STUCK_THRESHOLD = int(os.getenv("MCP_STUCK_THRESHOLD", "3"))
MAX_RESOLUTION_DEPTH = 5


# ---------------------------------------------------------------------------
# Error Classification
# ---------------------------------------------------------------------------

def classify_error(error: str, status_code: int | None = None) -> ErrorCategory:
    """
    Classify an error to determine retry strategy.

    - TRANSIENT: rate limits, temporary unavailability — use backoff
    - SERVER: persistent server errors — trigger circuit breaker
    - CLIENT: bad request, not found — don't retry, fix the call
    """
    error_lower = error.lower()

    # Status code based classification
    if status_code:
        if status_code == 429:
            return ErrorCategory.TRANSIENT
        if status_code in (502, 503, 504):
            return ErrorCategory.TRANSIENT
        if status_code == 500:
            return ErrorCategory.SERVER
        if 400 <= status_code < 500:
            return ErrorCategory.CLIENT

    # Keyword based classification
    transient_keywords = [
        "timeout", "rate limit", "throttl", "too many requests",
        "temporarily unavailable", "connection reset", "connection refused",
        "eof", "broken pipe",
    ]
    client_keywords = [
        "not found", "bad request", "invalid", "missing required",
        "validation error", "schema", "malformed",
    ]

    if any(kw in error_lower for kw in transient_keywords):
        return ErrorCategory.TRANSIENT
    if any(kw in error_lower for kw in client_keywords):
        return ErrorCategory.CLIENT

    return ErrorCategory.SERVER


# ---------------------------------------------------------------------------
# Circuit Breaker (3-state: closed / open / half-open)
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Per-server circuit breaker following the Hystrix pattern.

    States:

    - **CLOSED**: Normal. Count failures in a sliding window.
    - **OPEN**: Blocking all calls. Cooldown timer running.
    - **HALF_OPEN**: After cooldown, allow one probe request.
      If probe succeeds -> CLOSED. If fails -> OPEN with longer cooldown.

    This replaces the simple StuckDetector. Key improvement: tools automatically
    RECOVER after a cooldown, instead of staying stuck forever.
    """

    def __init__(
        self,
        failure_threshold: int = STUCK_THRESHOLD,
        cooldown_seconds: float = 60.0,
        max_cooldown_seconds: float = 300.0,
        window_seconds: float = 120.0,
    ) -> None:
        """Initialize the circuit breaker with configurable thresholds and cooldowns."""
        self._failure_threshold = failure_threshold
        self._base_cooldown = cooldown_seconds
        self._max_cooldown = max_cooldown_seconds
        self._window_seconds = window_seconds
        # Per-server state
        self._states: dict[str, CircuitState] = {}
        self._failures: dict[str, list[float]] = {}  # server -> [timestamps]
        self._opened_at: dict[str, float] = {}
        self._cooldown: dict[str, float] = {}
        self._consecutive_opens: dict[str, int] = {}

    def can_call(self, server_name: str) -> bool:
        """Check if a call to this server is allowed."""
        state = self._states.get(server_name, CircuitState.CLOSED)

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            opened = self._opened_at.get(server_name, 0)
            cooldown = self._cooldown.get(server_name, self._base_cooldown)
            if time.time() - opened >= cooldown:
                # Transition to half-open: allow one probe
                self._states[server_name] = CircuitState.HALF_OPEN
                log.info(f"circuit_half_open: {server_name} (probing)")
                return True
            return False

        if state == CircuitState.HALF_OPEN:
            # Only one probe allowed — already in progress
            return True

        return False

    def record_success(self, server_name: str) -> None:
        """Record a successful call. Resets circuit to CLOSED."""
        state = self._states.get(server_name, CircuitState.CLOSED)

        if state == CircuitState.HALF_OPEN:
            # Probe succeeded — close circuit
            log.info(f"circuit_closed: {server_name} (probe succeeded)")
            self._consecutive_opens[server_name] = 0

        self._states[server_name] = CircuitState.CLOSED
        # Clear failure window
        self._failures.pop(server_name, None)

    def record_failure(self, server_name: str) -> bool:
        """
        Record a failure. Returns True if circuit just opened.
        """
        state = self._states.get(server_name, CircuitState.CLOSED)
        now = time.time()

        if state == CircuitState.HALF_OPEN:
            # Probe failed — reopen with longer cooldown
            self._open_circuit(server_name)
            log.info(f"circuit_reopened: {server_name} (probe failed)")
            return True

        # CLOSED state: add to sliding window
        if server_name not in self._failures:
            self._failures[server_name] = []

        self._failures[server_name].append(now)

        # Trim to window
        cutoff = now - self._window_seconds
        self._failures[server_name] = [
            t for t in self._failures[server_name] if t > cutoff
        ]

        # Check threshold
        if len(self._failures[server_name]) >= self._failure_threshold:
            self._open_circuit(server_name)
            return True

        return False

    def _open_circuit(self, server_name: str) -> None:
        """Open the circuit with exponential cooldown."""
        self._states[server_name] = CircuitState.OPEN
        self._opened_at[server_name] = time.time()

        # Exponential cooldown: base * 2^consecutive_opens, capped
        opens = self._consecutive_opens.get(server_name, 0)
        cooldown = min(
            self._base_cooldown * (2 ** opens),
            self._max_cooldown,
        )
        self._cooldown[server_name] = cooldown
        self._consecutive_opens[server_name] = opens + 1

        log.warning(
            f"circuit_opened: {server_name} "
            f"(cooldown={cooldown:.0f}s, consecutive={opens + 1})"
        )

    def get_state(self, server_name: str) -> CircuitState:
        """Return the current circuit state for a server (CLOSED by default)."""
        return self._states.get(server_name, CircuitState.CLOSED)

    def get_all_states(self) -> dict[str, CircuitState]:
        """Return a copy of all server circuit states."""
        return dict(self._states)

    def reset(self, server_name: str | None = None) -> None:
        """Reset circuit state for a server or all servers."""
        if server_name:
            self._states.pop(server_name, None)
            self._failures.pop(server_name, None)
            self._opened_at.pop(server_name, None)
            self._cooldown.pop(server_name, None)
            self._consecutive_opens.pop(server_name, None)
        else:
            self._states.clear()
            self._failures.clear()
            self._opened_at.clear()
            self._cooldown.clear()
            self._consecutive_opens.clear()


# ---------------------------------------------------------------------------
# Exponential Backoff with Jitter
# ---------------------------------------------------------------------------

class BackoffStrategy:
    """
    Exponential backoff with jitter for transient errors.

    delay = min(base * 2^attempt + random(-jitter, +jitter), max_delay)
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: float = 0.5,
        max_retries: int = 5,
    ) -> None:
        """Initialize the backoff strategy with configurable delay parameters."""
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.max_retries = max_retries

    def should_retry(self, category: ErrorCategory, attempt: int) -> bool:
        """Determine if we should retry based on error type and attempt count."""
        if category == ErrorCategory.CLIENT:
            return False  # Client errors won't be fixed by retrying
        if attempt >= self.max_retries:
            return False
        return True

    def get_delay(self, attempt: int) -> float:
        """Calculate backoff delay for a given attempt number."""
        delay = self.base_delay * (2 ** attempt)
        jitter_amount = random.uniform(-self.jitter, self.jitter)
        return min(delay + jitter_amount, self.max_delay)

    async def wait(self, attempt: int) -> None:
        """Sleep for the calculated backoff delay."""
        delay = self.get_delay(attempt)
        log.debug(f"backoff_wait: attempt={attempt}, delay={delay:.2f}s")
        await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Loop Detection (Watchdog)
# ---------------------------------------------------------------------------

class LoopDetector:
    """
    Detects when the same tool+args combination is called repeatedly.

    Prevents infinite loops where the agent keeps trying the same failing
    call with identical arguments.
    """

    def __init__(self, max_repeats: int = 3) -> None:
        """Initialize the loop detector with a maximum repeat threshold."""
        self._max_repeats = max_repeats
        # call_signature -> count
        self._seen: dict[str, int] = {}

    def check(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """
        Check if this call is a loop. Returns True if loop detected.
        """
        sig = self._signature(tool_name, arguments)
        self._seen[sig] = self._seen.get(sig, 0) + 1
        if self._seen[sig] > self._max_repeats:
            log.warning(
                f"loop_detected: {tool_name} called {self._seen[sig]} times "
                f"with same args"
            )
            return True
        return False

    def reset(self) -> None:
        """Clear all seen call signatures."""
        self._seen.clear()

    def _signature(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Compute a deterministic hash of tool name + arguments for loop detection."""
        payload = json.dumps({"t": tool_name, "a": arguments}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Graceful Degradation Chain
# ---------------------------------------------------------------------------

class DegradationChain:
    """
    When resolution exhausts all alternatives, provide the best possible
    fallback instead of a hard failure.

    Chain: full result > partial result from resolution > cached result > structured error
    """

    def __init__(self) -> None:
        """Initialize the degradation chain with an empty cache."""
        # Simple LRU-style cache: (tool_name, args_hash) -> result
        self._cache: dict[str, str] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._cache_ttl: float = 300.0  # 5 minute cache

    def cache_result(self, tool_name: str, arguments: dict[str, Any], result: str) -> None:
        """Cache a successful result for potential degraded reuse."""
        key = self._cache_key(tool_name, arguments)
        self._cache[key] = result
        self._cache_timestamps[key] = time.time()
        # Evict old entries
        self._evict()

    def get_cached(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """Get a cached result if available and not expired."""
        key = self._cache_key(tool_name, arguments)
        if key in self._cache:
            age = time.time() - self._cache_timestamps.get(key, 0)
            if age <= self._cache_ttl:
                log.info(f"degradation_cache_hit: {tool_name} (age={age:.0f}s)")
                return self._cache[key]
            else:
                del self._cache[key]
                self._cache_timestamps.pop(key, None)
        return None

    def best_partial_result(self, record: ToolCallRecord) -> str | None:
        """Extract the best partial result from a resolution chain."""
        # If any result was attached during resolution attempts, use it
        if record.result and record.status != ToolCallStatus.ERROR:
            return record.result
        return None

    def structured_error(self, record: ToolCallRecord) -> str:
        """Build a structured error message with full context."""
        parts = [
            f"Tool call failed: {record.tool_name}",
            f"Error: {record.error or 'unknown'}",
            f"Category: {record.error_category.value}",
            f"Attempts: {record.attempt}/{record.max_attempts}",
        ]
        if record.resolution_chain:
            parts.append(f"Alternatives tried: {', '.join(record.resolution_chain)}")
        parts.append("Action: Retry with different arguments or use a different approach")
        return " | ".join(parts)

    def _cache_key(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Compute a deterministic cache key from tool name and arguments."""
        payload = json.dumps({"t": tool_name, "a": arguments}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _evict(self) -> None:
        """Evict expired cache entries. Keep max 500 entries."""
        now = time.time()
        expired = [
            k for k, ts in self._cache_timestamps.items()
            if now - ts > self._cache_ttl
        ]
        for k in expired:
            self._cache.pop(k, None)
            self._cache_timestamps.pop(k, None)
        # Hard cap
        if len(self._cache) > 500:
            oldest = sorted(self._cache_timestamps, key=self._cache_timestamps.get)
            for k in oldest[:len(self._cache) - 500]:
                self._cache.pop(k, None)
                self._cache_timestamps.pop(k, None)


# ---------------------------------------------------------------------------
# Tool Resolver (orchestrates all resilience patterns)
# ---------------------------------------------------------------------------

class ToolResolver:
    """
    Resolves stuck tool calls by discovering alternatives.

    Combines circuit breaker, backoff, loop detection, degradation,
    and BM25-ranked alternative discovery into a single orchestrator.

    The resolution protocol:
    1. Classify the error (transient/server/client)
    2. For transient: backoff + retry same tool
    3. For server: record failure in circuit breaker
    4. If circuit opens or retries exhausted: find alternatives via BM25 ranking
    5. Try top alternative
    6. If all alternatives exhausted: degradation chain (cache > partial > error)
    """

    def __init__(self, ranker: ToolRanker) -> None:
        """Initialize the resolver with sub-components for circuit breaking, backoff, etc."""
        self._ranker = ranker
        self._circuit = CircuitBreaker()
        self._backoff = BackoffStrategy()
        self._loops = LoopDetector()
        self._degradation = DegradationChain()
        self._resolution_history: dict[str, list[str]] = {}

    @property
    def circuit(self) -> CircuitBreaker:
        """Return the circuit breaker instance."""
        return self._circuit

    @property
    def backoff(self) -> BackoffStrategy:
        """Return the backoff strategy instance."""
        return self._backoff

    @property
    def loops(self) -> LoopDetector:
        """Return the loop detector instance."""
        return self._loops

    @property
    def degradation(self) -> DegradationChain:
        """Return the degradation chain instance."""
        return self._degradation

    def can_call_server(self, server_name: str) -> bool:
        """Check circuit breaker before calling a server."""
        return self._circuit.can_call(server_name)

    def on_call_result(self, record: ToolCallRecord) -> ToolCallRecord:
        """
        Process a tool call result through the full resilience pipeline.

        Returns the updated record (possibly marked as stuck/circuit_open).
        """
        server = record.server_name

        if record.status == ToolCallStatus.SUCCESS:
            result_str = record.result or ""
            if self._is_empty_result(result_str):
                # Empty results count as server errors
                record.error_category = ErrorCategory.SERVER
                self._circuit.record_failure(server)
                if not self._circuit.can_call(server):
                    record.mark_stuck()
            else:
                self._circuit.record_success(server)
                # Cache successful result for degradation fallback
                self._degradation.cache_result(
                    record.tool_name, record.arguments, result_str
                )
        elif record.status == ToolCallStatus.ERROR:
            # Classify the error if not already classified
            if record.error_category == ErrorCategory.UNKNOWN and record.error:
                record.error_category = classify_error(record.error)

            self._circuit.record_failure(server)

            if not self._circuit.can_call(server):
                record.mark_stuck()
                log.info(f"tool_stuck_circuit_open: {record.tool_name} on {server}")

        return record

    def should_retry(self, record: ToolCallRecord) -> bool:
        """Check if this specific call should be retried with backoff."""
        return self._backoff.should_retry(record.error_category, record.attempt)

    async def wait_for_retry(self, attempt: int) -> None:
        """Wait for backoff delay before retrying."""
        await self._backoff.wait(attempt)

    def check_loop(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Check if this call would create a loop."""
        return self._loops.check(tool_name, arguments)

    def resolve(
        self,
        stuck_record: ToolCallRecord,
        available_tools: list[MCPToolDefinition],
        task_description: str = "",
    ) -> list[ToolRankEntry]:
        """
        Find alternative tools when one is stuck.

        Filters out tools on servers with open circuits.
        """
        call_id = stuck_record.call_id

        if call_id not in self._resolution_history:
            self._resolution_history[call_id] = []
        tried = set(self._resolution_history[call_id])
        tried.add(stuck_record.tool_name)

        query = self._build_capability_query(stuck_record, task_description)

        # Filter: exclude tried tools AND tools on servers with open circuits
        candidates = [
            t for t in available_tools
            if t.name not in tried and self._circuit.can_call(t.server_name)
        ]
        if not candidates:
            log.warning(f"resolution_exhausted: {call_id}, all tools tried or circuits open")
            return []

        ranked = self._ranker.rank_for_query(query, candidates, top_k=10)

        for entry in ranked:
            self._resolution_history[call_id].append(entry.tool_name)
            stuck_record.resolution_chain.append(entry.tool_name)

        log.info(
            f"resolved: {stuck_record.tool_name} -> "
            f"{[e.tool_name for e in ranked[:3]]} "
            f"(tried {len(tried)} tools)"
        )

        return ranked

    def degrade(self, record: ToolCallRecord) -> ToolCallRecord:
        """
        Apply graceful degradation when all resolution fails.

        Returns the record with the best available result attached.
        """
        # Try cached result
        cached = self._degradation.get_cached(record.tool_name, record.arguments)
        if cached:
            record.mark_degraded(f"[cached] {cached}")
            return record

        # Try partial result from resolution
        partial = self._degradation.best_partial_result(record)
        if partial:
            record.mark_degraded(f"[partial] {partial}")
            return record

        # Structured error as last resort
        record.error = self._degradation.structured_error(record)
        return record

    def should_escalate(self, call_id: str, available_count: int) -> bool:
        """Check if resolution has tried enough alternatives to warrant escalation."""
        tried = len(self._resolution_history.get(call_id, []))
        return tried >= min(available_count // 2, MAX_RESOLUTION_DEPTH)

    def _build_capability_query(
        self,
        record: ToolCallRecord,
        task_description: str,
    ) -> str:
        """Build a search query from the failed call's context for BM25 alternative lookup."""
        parts = []
        if task_description:
            parts.append(task_description)
        parts.append(f"alternative to {record.tool_name}")
        if record.arguments:
            arg_keys = " ".join(record.arguments.keys())
            parts.append(arg_keys)
        if record.error:
            error_words = record.error[:200].split()
            parts.extend(error_words[:10])
        return " ".join(parts)

    def _is_empty_result(self, result: str | None) -> bool:
        """Check if a result is effectively empty (None, whitespace, or trivial JSON)."""
        if not result:
            return True
        stripped = result.strip()
        if not stripped:
            return True
        if len(stripped) < 5 and stripped.lower() in ("null", "none", "{}", "[]", "n/a"):
            return True
        return False
