"""
Hub-and-spoke tool calling orchestrator.

This is the core of the MCP tool calling protocol. It coordinates:
- Routing tool calls to the right MCP server
- Hub-and-spoke graph traversal (tools calling tools)
- Depth-limited recursion (200-1000 calls)
- Cross-referencing between MCP servers
- Ranking-informed tool selection
- Circuit breaker + backoff + stuck detection + resolution
- Per-server bulkhead isolation (semaphores)
- Watchdog timer + loop detection
- Graceful degradation chain
- Idempotency keys for safe retries
- MD file tracking of all calls

Architecture::

#                    ┌─────────────┐
#                    │ Orchestrator│ (Hub)
#                    │   (Router)  │
#                    └──────┬──────┘
#                           │
#        ┌──────────┬───────┼───────┬──────────┐
#        ▼          ▼       ▼       ▼          ▼
#   ┌─────────┐ ┌──────┐ ┌─────┐ ┌──────┐ ┌───────┐
#   │ MCP Srv │ │ MCP  │ │ MCP │ │ MCP  │ │  MCP  │ (Spokes)
#   │    A    │ │  B   │ │  C  │ │  D   │ │  ...  │
#   └─────────┘ └──────┘ └─────┘ └──────┘ └───────┘

References:
- Netflix Hystrix (circuit breaker + bulkhead)
- LangGraph (error edges, checkpoint recovery)
- AutoTool (tool inertia, sequential patterns)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional
from uuid import uuid4

import httpx

from oats.log import cl
from oats.mcp.models import (
    ErrorCategory,
    MCPToolDefinition,
    OrchestrationSession,
    ToolCallRecord,
    ToolCallStatus,
)
from oats.mcp.ranking import ToolRanker
from oats.mcp.registry import MCPServerRegistry
from oats.mcp.resolver import ToolResolver, classify_error
from oats.mcp.tracker import ToolCallTracker

log = cl("mcp.orchestrator")

MAX_CALL_DEPTH = int(os.getenv("MCP_MAX_CALL_DEPTH", "1000"))
SESSION_TIMEOUT = float(os.getenv("MCP_SESSION_TIMEOUT", "1800"))


class MCPOrchestrator:
    """
    Hub-and-spoke tool calling orchestrator.

    Manages the full lifecycle of tool calls across multiple MCP servers,
    including routing, execution, resilience, and tracking.
    """

    def __init__(
        self,
        registry: MCPServerRegistry,
        tracker: ToolCallTracker | None = None,
        ranker: ToolRanker | None = None,
    ) -> None:
        """Initialize the orchestrator with its registry, tracker, and ranker."""
        self._registry = registry
        self._tracker = tracker or ToolCallTracker()
        self._ranker = ranker or ToolRanker()
        self._resolver = ToolResolver(self._ranker)
        self._sessions: dict[str, OrchestrationSession] = {}
        # Per-server bulkhead semaphores
        self._server_semaphores: dict[str, asyncio.Semaphore] = {}

    async def initialize(self) -> None:
        """Initialize the orchestrator and discover tools."""
        if self._registry.needs_rediscovery:
            await self._registry.discover_all()
        tools = self._registry.list_tools()
        self._ranker.build_index(tools)
        # Create per-server semaphores
        for name, config in self._registry.list_servers().items():
            self._server_semaphores[name] = asyncio.Semaphore(config.max_concurrent)

    def create_session(
        self,
        session_id: str | None = None,
        timeout_seconds: float = SESSION_TIMEOUT,
    ) -> OrchestrationSession:
        """Create a new orchestration session."""
        sid = session_id or str(uuid4())
        session = OrchestrationSession(
            session_id=sid,
            timeout_seconds=timeout_seconds,
        )
        self._sessions[sid] = session
        self._tracker.init_session(session)
        log.info(f"session_created: {sid}")
        return session

    def get_session(self, session_id: str) -> OrchestrationSession | None:
        """Look up an orchestration session by ID."""
        return self._sessions.get(session_id)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str,
        parent_call_id: str | None = None,
        depth: int = 0,
        task_description: str = "",
    ) -> ToolCallRecord:
        """
        Execute a tool call with full orchestration.

        Flow:
        1. Guard: depth limit, watchdog timeout, loop detection
        2. Resolve tool definition
        3. Check circuit breaker for target server
        4. Acquire bulkhead semaphore
        5. Execute with retry (backoff for transient errors)
        6. On persistent failure: resolution via ranked alternatives
        7. On exhaustion: graceful degradation chain
        8. Track everything
        """
        session = self._sessions.get(session_id)
        if not session:
            session = self.create_session(session_id)

        # --- Guard: depth limit ---
        if depth >= MAX_CALL_DEPTH:
            return self._fail_record(
                tool_name, arguments, depth, parent_call_id,
                f"Max call depth ({MAX_CALL_DEPTH}) exceeded",
                ErrorCategory.CLIENT, session,
            )

        # --- Guard: watchdog timer ---
        if session.is_timed_out:
            return self._fail_record(
                tool_name, arguments, depth, parent_call_id,
                f"Session timed out ({session.timeout_seconds:.0f}s)",
                ErrorCategory.CLIENT, session,
            )

        # --- Guard: loop detection ---
        if self._resolver.check_loop(tool_name, arguments):
            return self._fail_record(
                tool_name, arguments, depth, parent_call_id,
                f"Loop detected: {tool_name} called repeatedly with same args",
                ErrorCategory.CLIENT, session,
            )

        # --- Resolve tool definition ---
        tool_def = self._registry.get_tool(tool_name)
        if not tool_def:
            candidates = self._registry.search_tools(tool_name)
            if candidates:
                tool_def = candidates[0]
                log.info(f"tool_resolved_via_search: {tool_name} -> {tool_def.name}")
            else:
                return self._fail_record(
                    tool_name, arguments, depth, parent_call_id,
                    f"Tool not found: {tool_name}",
                    ErrorCategory.CLIENT, session,
                )

        # --- Check circuit breaker ---
        if not self._resolver.can_call_server(tool_def.server_name):
            record = ToolCallRecord(
                call_id=str(uuid4()),
                tool_name=tool_def.name,
                server_name=tool_def.server_name,
                arguments=arguments,
                depth=depth,
                parent_call_id=parent_call_id,
            )
            record.mark_circuit_open(tool_def.server_name)
            # Try resolution immediately
            record.mark_stuck()
            record = await self._resolve_stuck(record, session, depth, task_description)
            self._ranker.record_call(record)
            session.add_record(record)
            self._tracker.record_call(session, record)
            return record

        # --- Create call record with idempotency key ---
        record = ToolCallRecord(
            call_id=str(uuid4()),
            tool_name=tool_def.name,
            server_name=tool_def.server_name,
            arguments=arguments,
            status=ToolCallStatus.RUNNING,
            depth=depth,
            parent_call_id=parent_call_id,
        )
        record.compute_idempotency_key()

        # --- Execute with retry + bulkhead ---
        record = await self._execute_with_retry(tool_def, record)

        # --- Check for stuck state via circuit breaker ---
        record = self._resolver.on_call_result(record)

        # --- If stuck, try resolution ---
        if record.status == ToolCallStatus.STUCK:
            record = await self._resolve_stuck(record, session, depth, task_description)

        # --- Update stats and tracking ---
        self._ranker.record_call(record)
        session.add_record(record)
        self._tracker.record_call(session, record)

        # Periodic ranking update
        if session.total_calls % 10 == 0:
            tools = self._registry.list_tools()
            index = self._ranker.build_index(tools)
            self._tracker.update_ranking(session, index)

        return record

    async def call_tool_chain(
        self,
        calls: list[dict[str, Any]],
        session_id: str,
        task_description: str = "",
    ) -> list[ToolCallRecord]:
        """Execute a chain of tool calls sequentially."""
        results: list[ToolCallRecord] = []

        for i, call in enumerate(calls):
            tool_name = call.get("tool", call.get("name", ""))
            arguments = call.get("arguments", call.get("args", {}))
            parent_id = results[-1].call_id if results else None

            record = await self.call_tool(
                tool_name=tool_name,
                arguments=arguments,
                session_id=session_id,
                parent_call_id=parent_id,
                depth=i,
                task_description=task_description,
            )
            results.append(record)

            # Stop chain on unrecoverable client error
            if (
                record.status == ToolCallStatus.ERROR
                and record.error_category == ErrorCategory.CLIENT
            ):
                log.warning(f"chain_stopped_at: {i}/{len(calls)} (client error)")
                break

        return results

    async def fan_out(
        self,
        tool_calls: list[dict[str, Any]],
        session_id: str,
        max_concurrent: int = 10,
    ) -> list[ToolCallRecord]:
        """Execute multiple tool calls concurrently (fan-out from hub)."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _limited_call(call: dict[str, Any]) -> ToolCallRecord:
            """Execute a single tool call under the concurrency semaphore."""
            async with semaphore:
                return await self.call_tool(
                    tool_name=call.get("tool", call.get("name", "")),
                    arguments=call.get("arguments", call.get("args", {})),
                    session_id=session_id,
                )

        results = await asyncio.gather(
            *[_limited_call(c) for c in tool_calls],
            return_exceptions=True,
        )

        records: list[ToolCallRecord] = []
        for r in results:
            if isinstance(r, Exception):
                record = ToolCallRecord(
                    call_id=str(uuid4()),
                    tool_name="unknown",
                    server_name="unknown",
                )
                record.mark_error(str(r), ErrorCategory.UNKNOWN)
                records.append(record)
            else:
                records.append(r)

        return records

    def rank_tools_for_task(
        self,
        task_description: str,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """Rank available tools for a given task description."""
        tools = self._registry.list_tools()
        ranked = self._ranker.rank_for_query(task_description, tools, top_k)
        return [
            {
                "tool_name": entry.tool_name,
                "server_name": entry.server_name,
                "score": entry.score,
                "relevance": entry.relevance_score,
                "reliability": entry.reliability_score,
                "inertia": entry.inertia_score,
            }
            for entry in ranked
        ]

    def get_tools_for_call(
        self,
        task_description: str = "",
        max_tools: int = 20,
        server_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get a reduced set of tool definitions for a LiteLLM chat completion call."""
        tools = self._registry.list_tools(server_name)
        if task_description:
            ranked = self._ranker.rank_for_query(task_description, tools, max_tools)
            selected_names = {e.tool_name for e in ranked}
            tools = [t for t in tools if t.name in selected_names]
        else:
            tools = tools[:max_tools]
        return [t.to_litellm_format() for t in tools]

    # --- Private methods ---

    async def _execute_with_retry(
        self,
        tool_def: MCPToolDefinition,
        record: ToolCallRecord,
    ) -> ToolCallRecord:
        """Execute a tool call with per-server bulkhead and retry logic."""
        server_name = tool_def.server_name
        max_attempts = self._resolver.backoff.max_retries

        # Ensure semaphore exists
        if server_name not in self._server_semaphores:
            config = self._registry.list_servers().get(server_name)
            max_concurrent = config.max_concurrent if config else 10
            self._server_semaphores[server_name] = asyncio.Semaphore(max_concurrent)

        semaphore = self._server_semaphores[server_name]

        for attempt in range(max_attempts):
            record.attempt = attempt + 1
            record.max_attempts = max_attempts

            # Acquire bulkhead semaphore
            async with semaphore:
                record = await self._execute_tool(tool_def, record)

            # Success — done
            if record.status == ToolCallStatus.SUCCESS:
                return record

            # Classify error
            if record.error and record.error_category == ErrorCategory.UNKNOWN:
                record.error_category = classify_error(record.error)

            # Don't retry client errors
            if not self._resolver.should_retry(record):
                return record

            # Backoff before retry
            if attempt < max_attempts - 1:
                await self._resolver.wait_for_retry(attempt)
                record.status = ToolCallStatus.RUNNING  # Reset for retry
                log.info(f"retrying: {tool_def.name} attempt={attempt + 2}/{max_attempts}")

        return record

    async def _execute_tool(
        self,
        tool_def: MCPToolDefinition,
        record: ToolCallRecord,
    ) -> ToolCallRecord:
        """Execute a tool call against its MCP server."""
        server_config = self._registry.list_servers().get(tool_def.server_name)
        if not server_config:
            record.mark_error(f"Server not found: {tool_def.server_name}", ErrorCategory.CLIENT)
            return record

        try:
            if server_config.url:
                result = await self._call_http_tool(
                    server_config.url,
                    tool_def,
                    record.arguments,
                    server_config.headers,
                    server_config.timeout_seconds,
                    record.idempotency_key,
                )
                record.mark_complete(result)
            elif server_config.command:
                result = await self._call_stdio_tool(
                    server_config,
                    tool_def,
                    record.arguments,
                )
                record.mark_complete(result)
            else:
                record.mark_error(
                    "Server has no URL or command configured",
                    ErrorCategory.CLIENT,
                )
        except asyncio.TimeoutError:
            record.mark_error(
                f"Timeout after {server_config.timeout_seconds}s",
                ErrorCategory.TRANSIENT,
            )
        except httpx.HTTPStatusError as e:
            category = classify_error(str(e), e.response.status_code)
            record.mark_error(str(e), category)
        except Exception as e:
            record.mark_error(str(e), ErrorCategory.SERVER)

        return record

    async def _call_http_tool(
        self,
        base_url: str,
        tool_def: MCPToolDefinition,
        arguments: dict[str, Any],
        headers: dict[str, str],
        timeout: int,
        idempotency_key: str | None = None,
    ) -> str:
        """
        Call a tool via HTTP MCP server with idempotency key.

        Uses the tool's call_endpoint for routing. For LiteLLM MCP functions
        this is /{mcp_function_name}/tools/call, NOT /mcp-rest/tools/call.
        """
        base = base_url.rstrip("/")

        # Use per-tool call endpoint from discovery (the fix for 404s)
        if tool_def.call_endpoint:
            call_path = tool_def.call_endpoint
        else:
            # Fallback: check route table
            route = self._registry.get_route(tool_def.name)
            if route and route.get("call_endpoint"):
                call_path = route["call_endpoint"]
            else:
                call_path = "/mcp-rest/tools/call"

        url = f"{base}{call_path}"

        # Strip server prefix from tool name for the actual call payload
        original_name = tool_def.name
        if "." in original_name:
            original_name = original_name.split(".", 1)[1]

        payload = {
            "name": original_name,
            "arguments": arguments,
        }

        log.info(f"http_call: {url} tool={original_name}")

        req_headers = dict(headers)
        if idempotency_key:
            req_headers["Idempotency-Key"] = idempotency_key

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=req_headers)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, str):
                return data
            if isinstance(data, dict):
                return json.dumps(
                    data.get("result", data.get("content", data.get("output", data))),
                    indent=2,
                )
            return json.dumps(data, indent=2)

    async def _call_stdio_tool(
        self,
        server_config: Any,
        tool_def: MCPToolDefinition,
        arguments: dict[str, Any],
    ) -> str:
        """Call a tool via stdio MCP server."""
        original_name = tool_def.name
        if "." in original_name:
            original_name = original_name.split(".", 1)[1]

        env = {**os.environ, **server_config.env}
        proc = await asyncio.create_subprocess_exec(
            server_config.command,
            *server_config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        init_msg = (
            '{"jsonrpc":"2.0","id":1,"method":"initialize",'
            '"params":{"protocolVersion":"2024-11-05",'
            '"capabilities":{},"clientInfo":{"name":"coder","version":"1.0"}}}\n'
        )
        proc.stdin.write(init_msg.encode())
        await proc.stdin.drain()
        await asyncio.wait_for(proc.stdout.readline(), timeout=10)

        proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        await proc.stdin.drain()

        call_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": original_name, "arguments": arguments},
        }) + "\n"

        proc.stdin.write(call_msg.encode())
        await proc.stdin.drain()

        resp_line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
        proc.terminate()

        data = json.loads(resp_line)
        result = data.get("result", {})
        content = result.get("content", [])
        if content and isinstance(content, list):
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts)
        return json.dumps(result, indent=2)

    async def _resolve_stuck(
        self,
        record: ToolCallRecord,
        session: OrchestrationSession,
        depth: int,
        task_description: str,
    ) -> ToolCallRecord:
        """
        Attempt to resolve a stuck tool call.

        Protocol:
        1. Check escalation threshold
        2. Get ranked alternatives (filtered by circuit breaker state)
        3. Try top alternative
        4. If all fail: graceful degradation chain
        """
        available_tools = self._registry.list_tools()

        if self._resolver.should_escalate(record.call_id, len(available_tools)):
            log.warning(f"resolution_escalated: {record.call_id}")
            return self._resolver.degrade(record)

        alternatives = self._resolver.resolve(record, available_tools, task_description)

        if not alternatives:
            return self._resolver.degrade(record)

        best = alternatives[0]
        log.info(
            f"trying_alternative: {best.tool_name} "
            f"(score={best.score:.3f}) for stuck {record.tool_name}"
        )

        alt_record = await self.call_tool(
            tool_name=best.tool_name,
            arguments=record.arguments,
            session_id=session.session_id,
            parent_call_id=record.call_id,
            depth=depth + 1,
            task_description=task_description,
        )

        if alt_record.status in (ToolCallStatus.SUCCESS, ToolCallStatus.DEGRADED):
            record.status = ToolCallStatus.RESOLVED
            record.result = f"Resolved via {best.tool_name}: {alt_record.result}"
            record.completed_at = time.time()
            record.latency_ms = (record.completed_at - record.started_at) * 1000

        return record

    def _fail_record(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        depth: int,
        parent_call_id: str | None,
        error: str,
        category: ErrorCategory,
        session: OrchestrationSession,
    ) -> ToolCallRecord:
        """Create a failed record and track it."""
        record = ToolCallRecord(
            call_id=str(uuid4()),
            tool_name=tool_name,
            server_name="",
            arguments=arguments,
            depth=depth,
            parent_call_id=parent_call_id,
        )
        record.mark_error(error, category)
        session.add_record(record)
        self._tracker.record_call(session, record)
        return record

    # --- Session summary ---

    def get_session_summary(self, session_id: str) -> dict[str, Any]:
        """Get a summary of an orchestration session."""
        session = self._sessions.get(session_id)
        if not session:
            return {"error": "Session not found"}

        completed = [
            r for r in session.call_records
            if r.status in (ToolCallStatus.SUCCESS, ToolCallStatus.RESOLVED, ToolCallStatus.DEGRADED)
        ]
        errors = [r for r in session.call_records if r.status == ToolCallStatus.ERROR]
        stuck = [r for r in session.call_records if r.status == ToolCallStatus.STUCK]
        circuit_open = [r for r in session.call_records if r.status == ToolCallStatus.CIRCUIT_OPEN]

        return {
            "session_id": session_id,
            "total_calls": session.total_calls,
            "max_depth": session.max_depth,
            "successes": len(completed),
            "errors": len(errors),
            "stuck": len(stuck),
            "circuit_open": len(circuit_open),
            "success_rate": len(completed) / max(session.total_calls, 1),
            "duration_seconds": time.time() - session.started_at,
            "circuit_states": {
                name: state.value
                for name, state in self._resolver.circuit.get_all_states().items()
            },
        }
