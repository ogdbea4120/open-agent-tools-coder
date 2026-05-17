"""
Planning mode tools for creating implementation plans before execution.

Provides three tools for the planning workflow:

- :class:`PlanEnterTool` — Enter planning mode and create a plan file.
- :class:`PlanExitTool` — Exit planning mode and request user approval.
- :class:`PlanStatusTool` — Check the current planning mode status.

Helper functions:

- :func:`is_planning_mode` — Check if a session is in planning mode.
- :func:`get_plan_state` — Get the full planning state for a session.
"""

from __future__ import annotations

import aiofiles
from pathlib import Path
from typing import Any
from datetime import datetime
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.core.storage import KeyValueStorage
from oats.log import cl

log = cl('tool.plan')


# Storage for planning mode state
_plan_storage = KeyValueStorage("plans")


class PlanEnterTool(Tool):
    """Enter planning mode to create an implementation plan.

    Creates a skeleton plan file and stores the planning state in
    session-scoped storage. While in planning mode, file-modifying
    tools are blocked.

    Example:
        ::

            plan_enter reason="Adding user authentication feature"
    """

    @property
    def name(self) -> str:
        return "plan_enter"

    @property
    def description(self) -> str:
        return """Enter planning mode to create an implementation plan.

Use this when:
- Starting a complex task that needs careful planning
- The user asks for a plan before implementation
- You need to explore the codebase before making changes

In planning mode:
- You can read files and explore the codebase
- You CANNOT modify files (write, edit, bash commands that modify files)
- Use plan_exit when the plan is ready for approval

This ensures the user can review the approach before any changes are made."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why planning mode is being entered",
                },
                "plan_file": {
                    "type": "string",
                    "description": "Optional path for the plan file (default: .coder/plan.md)",
                },
            },
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Enter planning mode and create an initial plan file.

        Creates a skeleton plan file at the specified path (default ``.coder/plan.md``)
        and stores the planning state in session-scoped storage. While in planning mode,
        file-modifying tools are blocked.

        Args:
            args: May contain ``reason`` (str) and ``plan_file`` (str, path for the plan file).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` confirming entry into planning mode with instructions.
        """
        reason = args.get("reason", "Creating implementation plan")
        plan_file = args.get("plan_file", ".coder/plan.md")

        # Check if already in planning mode
        state = await _plan_storage.get(ctx.session_id)
        if state and state.get("active"):
            return ToolResult(
                title="PlanEnter",
                output="Already in planning mode.",
                metadata={"active": True, "plan_file": state.get("plan_file")},
            )

        # Enter planning mode
        plan_path = ctx.working_dir / plan_file
        plan_path.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "active": True,
            "entered_at": datetime.utcnow().isoformat(),
            "reason": reason,
            "plan_file": str(plan_path),
            "session_id": ctx.session_id,
        }
        await _plan_storage.set(ctx.session_id, state)

        # Create initial plan file
        initial_content = f"""# Implementation Plan

Created: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}

## Objective

{reason}

## Analysis

(Analyzing the codebase...)

## Approach

(Planning the implementation...)

## Steps

1. [ ] Step 1
2. [ ] Step 2
3. [ ] Step 3

## Files to Modify

- file1.py
- file2.py

## Risks and Considerations

-

---
*This plan requires approval before implementation.*
"""
        log.info(f'plan_create_file:\n{plan_path}\nreason:\n{reason}')
        async with aiofiles.open(plan_path, "w") as f:
            await f.write(initial_content)

        return ToolResult(
            title="PlanEnter",
            output=f"""Entered planning mode.

Reason: {reason}
Plan file: {plan_file}

In planning mode, you can:
- Read and explore files
- Search the codebase
- Update the plan file

You CANNOT:
- Modify files (except the plan file)
- Run destructive commands

Use the plan file to document:
1. Your analysis of the codebase
2. The proposed approach
3. Step-by-step implementation plan
4. Files that will be modified

When the plan is complete, use plan_exit to request approval.""",
            metadata=state,
        )


class PlanExitTool(Tool):
    """Exit planning mode and request user approval for the plan.

    Deactivates the planning state, allowing file-modifying tools to
    resume. Presents the plan summary for user review.

    Example:
        ::

            plan_exit summary="Plan to add auth: 3 steps, 4 files modified"
    """

    @property
    def name(self) -> str:
        return "plan_exit"

    @property
    def description(self) -> str:
        return """Exit planning mode and request user approval for the plan.

Use this when:
- The implementation plan is complete
- You're ready for the user to review and approve

The user will review the plan and can:
- Approve: Proceed with implementation
- Request changes: Continue planning
- Cancel: Abort the task"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of the plan",
                },
            },
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Exit planning mode and present the plan for user approval.

        Reads the plan file content, deactivates planning mode, and sets the
        session state to ``awaiting_approval``. The user can then approve,
        request changes, or cancel.

        Args:
            args: May contain ``summary`` (str) — a brief summary of the plan.
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the plan content and approval options.
        """
        summary = args.get("summary", "")

        # Check if in planning mode
        state = await _plan_storage.get(ctx.session_id)
        if not state or not state.get("active"):
            return ToolResult(
                title="PlanExit",
                output="Not in planning mode.",
                error="Not in planning mode. Use plan_enter first.",
            )

        plan_file = state.get("plan_file", "")

        # Read the plan content
        plan_content = ""
        if plan_file:
            plan_path = Path(plan_file)
            log.info(f'plan_exec_file:\n{plan_path}')
            if plan_path.exists():
                async with aiofiles.open(plan_path, "r") as f:
                    plan_content = await f.read()

        # Exit planning mode
        state["active"] = False
        state["exited_at"] = datetime.utcnow().isoformat()
        state["summary"] = summary
        state["awaiting_approval"] = True
        await _plan_storage.set(ctx.session_id, state)

        output_lines = [
            "Plan ready for review.",
            "",
            f"Plan file: {plan_file}",
            "",
        ]

        if summary:
            output_lines.extend(["Summary:", summary, ""])

        output_lines.extend([
            "---",
            "Plan Content:",
            "---",
            plan_content[:2000] if plan_content else "(No plan content)",
            "",
            "---",
            "",
            "Waiting for user approval to proceed with implementation.",
            "",
            "Options:",
            "- Approve: Type 'approve' or 'yes' to proceed",
            "- Modify: Provide feedback to update the plan",
            "- Cancel: Type 'cancel' to abort",
        ])

        return ToolResult(
            title="PlanExit",
            output="\n".join(output_lines),
            metadata={
                **state,
                "plan_content_preview": plan_content[:500] if plan_content else "",
            },
        )


class PlanStatusTool(Tool):
    """Check the current planning mode status for the session.

    Returns whether the session is in planning mode, the plan file path,
    the reason for entering planning mode, and any summary information.

    Example:
        ::

            plan_status
    """

    @property
    def name(self) -> str:
        return "plan_status"

    @property
    def description(self) -> str:
        return """Check if currently in planning mode and get the plan status."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Check the current planning mode status for the session.

        Args:
            args: Unused (no parameters required).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the planning mode status and metadata.
        """
        state = await _plan_storage.get(ctx.session_id)

        if not state:
            return ToolResult(
                title="PlanStatus",
                output="Not in planning mode.",
                metadata={"active": False},
            )

        is_active = state.get("active", False)
        awaiting_approval = state.get("awaiting_approval", False)
        plan_file = state.get("plan_file", "")

        if is_active:
            status = "Active - Planning in progress"
        elif awaiting_approval:
            status = "Awaiting Approval"
        else:
            status = "Inactive"

        output_lines = [
            f"Planning Mode: {status}",
            f"Plan File: {plan_file}",
        ]

        if state.get("reason"):
            output_lines.append(f"Reason: {state['reason']}")
        if state.get("entered_at"):
            output_lines.append(f"Started: {state['entered_at']}")
        if state.get("summary"):
            output_lines.append(f"Summary: {state['summary']}")

        log.info(f'plan_status_file:\n{ctx.session_id}')
        return ToolResult(
            title="PlanStatus",
            output="\n".join(output_lines),
            metadata=state,
        )


async def is_planning_mode(session_id: str) -> bool:
    """Check if a session is currently in planning mode.

    Args:
        session_id: The session identifier.

    Returns:
        ``True`` if the session has an active planning state.
    """
    state = await _plan_storage.get(session_id)
    return state is not None and state.get("active", False)


async def get_plan_state(session_id: str) -> dict[str, Any] | None:
    """Get the full planning state for a session.

    Args:
        session_id: The session identifier.

    Returns:
        The planning state dict, or ``None`` if no state exists.
    """
    return await _plan_storage.get(session_id)
