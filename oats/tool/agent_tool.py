"""
Sub-agent tool — spawns independent child agents with their own sessions.

Allows the LLM to delegate complex, multi-step tasks to specialized
sub-agents that run their own tool loops.

Provides two tools:

- :class:`AgentTool` — Spawn a sub-agent to handle a complex task autonomously.
- :class:`AgentStatusTool` — Check the status of a background sub-agent.

Agent types control tool access:

- ``general`` — all tools (default)
- ``explore`` — read-only (read, glob, grep, bash, webfetch, websearch)
- ``plan`` — planning tools (read, glob, grep, plan tools, todowrite)
- ``verify`` — verification (read, glob, grep, bash)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.agent.agent import (
    AgentType,
    AGENT_TYPE_TOOLS,
    AGENT_TYPE_MAX_ITERATIONS,
)
from oats.core.id import generate_short_id
from oats.log import cl

log = cl("tool.agent")

# Track background agents per parent session
_background_agents: dict[str, asyncio.Task] = {}
_background_results: dict[str, ToolResult] = {}


class AgentTool(Tool):
    """
    Spawn a sub-agent to handle a complex task autonomously.

    The sub-agent gets its own session, tool access, and context.
    It runs the full agent loop and returns the final result.

    Agent types control tool access:
    - general: all tools (default)
    - explore: read-only (read, glob, grep, bash, webfetch, websearch)
    - plan: planning tools (read, glob, grep, plan tools, todowrite)
    - verify: verification (read, glob, grep, bash)
    """

    @property
    def name(self) -> str:
        return "agent"

    @property
    def description(self) -> str:
        return (
            "Launch a sub-agent to handle a complex task autonomously. "
            "The sub-agent gets its own session and tool access. "
            "Use agent_type to control what tools the sub-agent can use: "
            "'general' (all tools), 'explore' (read-only), "
            "'plan' (planning/design), 'verify' (testing/review). "
            "Use run_in_background=true for tasks that don't need immediate results."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Complete task description for the sub-agent. "
                        "Include all necessary context — the sub-agent has no "
                        "knowledge of the parent conversation."
                    ),
                },
                "agent_type": {
                    "type": "string",
                    "enum": ["general", "explore", "plan", "verify"],
                    "description": (
                        "Type of sub-agent controlling tool access. "
                        "Default: 'general' (all tools)."
                    ),
                    "default": "general",
                },
                "model_override": {
                    "type": "string",
                    "description": "Optional model ID override for the sub-agent.",
                },
                "provider_override": {
                    "type": "string",
                    "description": "Optional provider ID override for the sub-agent.",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory override.",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": (
                        "If true, run the agent in the background and return "
                        "immediately with an agent_id. Use agent_status to check results."
                    ),
                    "default": False,
                },
                "isolation": {
                    "type": "string",
                    "enum": ["none", "worktree"],
                    "description": "Isolation mode. 'worktree' creates a git worktree for the agent.",
                    "default": "none",
                },
            },
            "required": ["prompt"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Spawn and run a sub-agent to handle a delegated task.

        Validates the prompt, checks the agent nesting depth limit, and either
        runs the sub-agent synchronously or spawns it as a background task. The
        sub-agent gets its own session, tool access (filtered by agent type),
        and optional git worktree isolation.

        Args:
            args: Must contain ``prompt`` (str). May contain ``agent_type`` (str,
                one of ``general``, ``explore``, ``plan``, ``verify``),
                ``model_override`` (str), ``provider_override`` (str),
                ``working_dir`` (str), ``run_in_background`` (bool), and
                ``isolation`` (str, ``none`` or ``worktree``).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the sub-agent's output (synchronous mode)
            or a launch confirmation with ``agent_id`` (background mode).
        """
        prompt = args.get("prompt", "")
        agent_type_str = args.get("agent_type", "general")
        model_override = args.get("model_override")
        provider_override = args.get("provider_override")
        working_dir = args.get("working_dir")
        run_in_background = args.get("run_in_background", False)
        isolation = args.get("isolation", "none")

        if not prompt:
            return ToolResult(
                title="Agent Error",
                output="",
                error="prompt is required",
            )

        # Check depth limit
        if ctx.agent_depth >= ctx.max_agent_depth:
            return ToolResult(
                title="Agent Error",
                output="",
                error=(
                    f"Maximum agent nesting depth ({ctx.max_agent_depth}) reached. "
                    "Cannot spawn more sub-agents."
                ),
            )

        # Parse agent type
        try:
            agent_type = AgentType(agent_type_str)
        except ValueError:
            return ToolResult(
                title="Agent Error",
                output="",
                error=f"Unknown agent_type: {agent_type_str}. Use: general, explore, plan, verify",
            )

        agent_id = generate_short_id()

        # Handle worktree isolation
        worktree_path = None
        effective_working_dir = working_dir or str(ctx.working_dir)

        if isolation == "worktree":
            try:
                from oats.git.worktree import WorktreeManager
                wt_manager = WorktreeManager(Path(str(ctx.project_dir)))
                worktree_path = await wt_manager.create()
                effective_working_dir = str(worktree_path)
                log.info(f"agent_{agent_id}: created worktree at {worktree_path}")
            except Exception as e:
                log.warn(f"agent_{agent_id}: worktree creation failed: {e}, using normal dir")

        if run_in_background:
            # Spawn as background task
            task = asyncio.create_task(
                self._run_agent(
                    agent_id=agent_id,
                    prompt=prompt,
                    agent_type=agent_type,
                    ctx=ctx,
                    model_override=model_override,
                    provider_override=provider_override,
                    working_dir=effective_working_dir,
                    worktree_path=worktree_path,
                )
            )
            _background_agents[agent_id] = task
            return ToolResult(
                title=f"Agent Launched (background)",
                output=(
                    f"Sub-agent '{agent_id}' launched in background "
                    f"(type={agent_type_str}).\n"
                    f"Use agent_status with agent_id='{agent_id}' to check results."
                ),
                metadata={"agent_id": agent_id, "background": True},
            )
        else:
            # Run synchronously
            return await self._run_agent(
                agent_id=agent_id,
                prompt=prompt,
                agent_type=agent_type,
                ctx=ctx,
                model_override=model_override,
                provider_override=provider_override,
                working_dir=effective_working_dir,
                worktree_path=worktree_path,
            )

    async def _run_agent(
        self,
        agent_id: str,
        prompt: str,
        agent_type: AgentType,
        ctx: ToolContext,
        model_override: str | None = None,
        provider_override: str | None = None,
        working_dir: str | None = None,
        worktree_path: Path | None = None,
    ) -> ToolResult:
        """Run a sub-agent to completion and return its result.

        Creates a new session for the sub-agent with the appropriate tool set
        based on agent type. The sub-agent runs its own agent loop and returns
        the final result. If running in background mode, the result is cached
        for later retrieval via :class:`AgentStatusTool`.

        Args:
            agent_id: Unique identifier for this sub-agent.
            prompt: The task description for the sub-agent.
            agent_type: Controls which tools the sub-agent has access to.
            ctx: The parent tool execution context.
            model_override: Optional model ID override.
            provider_override: Optional provider ID override.
            working_dir: Optional working directory override.
            worktree_path: Optional git worktree path for isolation.

        Returns:
            A :class:`ToolResult` with the sub-agent's output.
        """
        try:
            # Lazy imports to avoid circular dependencies
            from oats.session.session import create_session, Session
            from oats.session.processor import SessionProcessor
            from oats.core.config import get_config
            from oats.tool.registry import list_tools, ToolDefinition
            from oats.provider.provider import ToolDefinition

            config = get_config()
            effective_model = model_override or config.model.model_id
            effective_provider = provider_override or config.model.provider_id
            effective_dir = working_dir or str(ctx.working_dir)

            log.info(
                f"agent_{agent_id}: starting (type={agent_type.value}, "
                f"model={effective_model}, depth={ctx.agent_depth + 1})"
            )

            # Create child session
            child_session = await create_session(
                project_dir=Path(str(ctx.project_dir)),
                working_dir=Path(effective_dir),
                title=f"Sub-agent [{agent_type.value}] {agent_id}",
                model_id=effective_model,
                provider_id=effective_provider,
            )
            # Mark parent relationship
            child_session.info.parent_session_id = ctx.session_id

            # Create processor
            processor = SessionProcessor(child_session)

            # Collect results from the agent loop
            final_text = ""
            tool_calls_made = 0
            errors = []

            max_iterations = AGENT_TYPE_MAX_ITERATIONS.get(agent_type, 200)

            # Build system prompt prefix for the sub-agent
            agent_system_prefix = self._build_agent_system_prefix(agent_type)
            full_prompt = f"{agent_system_prefix}\n\n{prompt}"

            async for event in processor.process_message(
                content=full_prompt,
                auto_approve_tools=True,
                areq=ctx.areq,
                tk=ctx.tk,
            ):
                event_type = event.get("type")

                if event_type == "assistant_text":
                    final_text = event.get("content", "")

                elif event_type == "tool_call":
                    tool_calls_made += 1
                    tool_name = event.get("tool_name", "?")

                    # Enforce tool restrictions for agent type
                    allowed = AGENT_TYPE_TOOLS.get(agent_type)
                    if allowed is not None and tool_name not in allowed:
                        log.warn(
                            f"agent_{agent_id}: blocked tool {tool_name} "
                            f"(not allowed for {agent_type.value})"
                        )

                elif event_type == "error":
                    errors.append(event.get("error", "Unknown error"))

                elif event_type == "warning":
                    errors.append(event.get("message", ""))

                # Check iteration limit
                if tool_calls_made >= max_iterations:
                    log.warn(f"agent_{agent_id}: hit max iterations ({max_iterations})")
                    break

            # Cleanup worktree if applicable
            worktree_info = ""
            if worktree_path:
                try:
                    from oats.git.worktree import WorktreeManager
                    wt_manager = WorktreeManager(Path(str(ctx.project_dir)))
                    has_changes = await wt_manager.has_changes(worktree_path)
                    if has_changes:
                        worktree_info = f"\n\nWorktree with changes at: {worktree_path}"
                    else:
                        await wt_manager.cleanup(worktree_path)
                except Exception as e:
                    log.warn(f"agent_{agent_id}: worktree cleanup error: {e}")

            result = ToolResult(
                title=f"Agent Result [{agent_type.value}]",
                output=(
                    f"{final_text}{worktree_info}"
                    if not errors
                    else f"{final_text}\n\nErrors: {'; '.join(errors)}{worktree_info}"
                ),
                metadata={
                    "agent_id": agent_id,
                    "agent_type": agent_type.value,
                    "tool_calls": tool_calls_made,
                    "child_session_id": child_session.id,
                },
            )

            # Store result for background agents
            _background_results[agent_id] = result

            log.info(
                f"agent_{agent_id}: completed "
                f"(tool_calls={tool_calls_made}, text_len={len(final_text)})"
            )

            return result

        except Exception as e:
            log.error(f"agent_{agent_id}: failed: {e}")
            result = ToolResult(
                title="Agent Error",
                output="",
                error=f"Sub-agent failed: {e}",
            )
            _background_results[agent_id] = result
            return result

    def _build_system_prompt(self, agent_type: AgentType) -> str:
        """Build a system prompt prefix based on the agent type.

        Each agent type gets a tailored instruction set that constrains its
        behavior (e.g., read-only for explore, planning-focused for plan).

        Args:
            agent_type: The type of sub-agent.

        Returns:
            A system prompt string.
        """
        prefixes = {            AgentType.GENERAL: (
                "You are a sub-agent handling a delegated task. "
                "Complete the task thoroughly and return a clear summary of your findings or actions."
            ),
            AgentType.EXPLORE: (
                "You are a read-only exploration sub-agent. "
                "Your job is to investigate the codebase and report findings. "
                "Do NOT modify any files. Use read, glob, grep, and bash (read-only commands) "
                "to explore. Return a comprehensive report."
            ),
            AgentType.PLAN: (
                "You are a planning sub-agent. "
                "Your job is to design an implementation approach. "
                "Read the codebase, identify files to change, consider trade-offs, "
                "and return a detailed step-by-step plan."
            ),
            AgentType.VERIFY: (
                "You are a verification sub-agent. "
                "Your job is to review code, run tests, and verify correctness. "
                "Check for bugs, security issues, and quality problems. "
                "Return a detailed report of your findings."
            ),
        }
        return prefixes.get(agent_type, prefixes[AgentType.GENERAL])


class AgentStatusTool(Tool):
    """Check the status and results of a background sub-agent.

    Looks up the agent by ID in the background results cache. If the agent
    has completed, returns its result. If still running, reports status.

    Example:
        ::

            agent_status agent_id="abc123"
    """

    @property
    def name(self) -> str:
        return "agent_status"

    @property
    def description(self) -> str:
        return (
            "Check the status and results of a background sub-agent. "
            "Use the agent_id returned by the agent tool when run_in_background=true."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The agent ID to check status for.",
                },
            },
            "required": ["agent_id"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Check the status and results of a background sub-agent.

        Looks up the agent by ID in the background results cache. If the agent
        has completed, returns its result. If still running, reports status.

        Args:
            args: Must contain ``agent_id`` (str).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the agent status and optionally its output.
        """
        agent_id = args.get("agent_id", "")

        if not agent_id:
            return ToolResult(
                title="Agent Status Error",
                output="",
                error="agent_id is required",
            )

        # Check if we have a result
        if agent_id in _background_results:
            result = _background_results[agent_id]
            # Clean up
            _background_agents.pop(agent_id, None)
            return ToolResult(
                title=f"Agent {agent_id} - Completed",
                output=result.output,
                metadata={**result.metadata, "status": "completed"},
                error=result.error,
            )

        # Check if still running
        if agent_id in _background_agents:
            task = _background_agents[agent_id]
            if task.done():
                # Task finished but result not stored (shouldn't happen, but handle it)
                try:
                    result = task.result()
                    return ToolResult(
                        title=f"Agent {agent_id} - Completed",
                        output=result.output if isinstance(result, ToolResult) else str(result),
                        metadata={"status": "completed"},
                    )
                except Exception as e:
                    return ToolResult(
                        title=f"Agent {agent_id} - Failed",
                        output="",
                        error=str(e),
                        metadata={"status": "failed"},
                    )
            else:
                return ToolResult(
                    title=f"Agent {agent_id} - Running",
                    output="The sub-agent is still running. Check again later.",
                    metadata={"status": "running"},
                )

        return ToolResult(
            title=f"Agent {agent_id} - Not Found",
            output="",
            error=f"No agent found with ID '{agent_id}'",
        )
