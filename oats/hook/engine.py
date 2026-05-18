"""
Hook engine — executes user-defined commands at lifecycle events.

Hooks are configured in coder.json::

    {
      "hooks": [
        {
          "event": "pre_tool_use",
          "matcher": "bash",
          "command": "/path/to/script.sh",
          "timeout": 30
        }
      ]
    }

Hook commands receive a JSON context on stdin and must return JSON on stdout::

    {
      "action": "continue",
      "modified_args": {},
      "message": "..."
    }
"""
from __future__ import annotations

import asyncio
import fnmatch
import ujson as json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Union
from oats.log import cl

log = cl("hook.engine")

HookHandler = Callable[["HookContext"], Union[Optional["HookResult"], Awaitable[Optional["HookResult"]]]]


class HookEvent(str, Enum):
    """Lifecycle events that can trigger hooks."""

    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    SESSION_START = "session_start"
    FILE_CHANGED = "file_changed"
    ASSISTANT_RESPONSE = 'assistant_response'


@dataclass
class HookContext:
    """Context passed to hook commands."""

    session_id: str
    event: HookEvent
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result_output: str | None = None
    tool_result_error: str | None = None
    user_prompt: str | None = None
    assistant_response: str | None = None
    root_session_id: str | None = None
    file_path: str | None = None
    working_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the hook context to a plain dict for JSON encoding."""
        return {
            "session_id": self.session_id,
            "event": self.event.value,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result_output": self.tool_result_output,
            "tool_result_error": self.tool_result_error,
            "user_prompt": self.user_prompt,
            "assistant_response": self.assistant_response,
            "root_session_id": self.root_session_id,
            "file_path": self.file_path,
            "working_dir": self.working_dir,
        }


@dataclass
class HookResult:
    """Result returned by a hook command."""

    action: str = "continue"  # "continue" | "block" | "modify"
    modified_args: dict[str, Any] | None = None
    message: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HookResult":
        """Deserialize a HookResult from a JSON dict."""
        return cls(
            action=data.get("action", "continue"),
            modified_args=data.get("modified_args"),
            message=data.get("message"),
        )

    @classmethod
    def continue_result(cls) -> "HookResult":
        """Return a HookResult that signals the agent to continue."""
        return cls(action="continue")

    @classmethod
    def block_result(cls, message: str = "") -> "HookResult":
        """Return a HookResult that signals the agent to stop."""
        return cls(action="block", message=message)


class HookEngine:
    """
    Executes hook commands at lifecycle events.

    Hooks are loaded from configuration and matched against events
    and optional tool name patterns.
    """

    def __init__(self, hooks: list[dict[str, Any]] | None = None) -> None:
        self._hooks = hooks or []

    async def fire(self, event: HookEvent, context: HookContext) -> HookResult:
        """
        Fire all hooks matching this event.

        Returns the first blocking result, or continue if all pass.
        For pre_tool_use with "modify" action, returns modified args.
        """
        matching = self._get_matching_hooks(event, context)

        if not matching:
            return HookResult.continue_result()

        for hook in matching:
            try:
                result = await self._execute_hook(hook, context)
                if result.action == "block":
                    log.info(
                        f"hook_blocked: event={event.value} "
                        f"tool={context.tool_name} msg={result.message}"
                    )
                    return result
                if result.action == "modify" and result.modified_args is not None:
                    log.info(
                        f"hook_modified: event={event.value} "
                        f"tool={context.tool_name}"
                    )
                    return result
            except Exception as e:
                log.error(f"hook_error: event={event.value} error={e}")
                # Hook errors don't block execution
                continue

        return HookResult.continue_result()

    def _get_matching_hooks(
        self, event: HookEvent, context: HookContext
    ) -> list[dict[str, Any]]:
        """Get hooks that match the given event and context."""
        matching = []
        for hook in self._hooks:
            hook_event = hook.get("event", "")
            if hook_event != event.value:
                continue

            # Check tool name matcher (optional)
            matcher = hook.get("matcher")
            if matcher and context.tool_name:
                if not fnmatch.fnmatch(context.tool_name, matcher):
                    continue
            elif matcher and not context.tool_name:
                # Hook has a matcher but event has no tool name — skip
                continue

            matching.append(hook)

        return matching

    async def _execute_hook(
        self, hook: dict[str, Any], context: HookContext
    ) -> HookResult:
        """Execute a single hook command."""
        command = hook.get("command")
        if not command:
            return HookResult.continue_result()

        timeout = hook.get("timeout", 30)

        # Serialize context to JSON
        context_json = json.dumps(context.to_dict())

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=context_json.encode()),
                timeout=timeout,
            )

            if process.returncode != 0:
                log.warn(
                    f"hook_cmd_failed: cmd={command} "
                    f"rc={process.returncode} stderr={stderr.decode()[:200]}"
                )
                return HookResult.continue_result()

            # Parse JSON output
            output = stdout.decode().strip()
            if not output:
                return HookResult.continue_result()

            try:
                data = json.loads(output)
                return HookResult.from_dict(data)
            except json.JSONDecodeError:
                log.warn(f"hook_invalid_json: cmd={command} output={output[:200]}")
                return HookResult.continue_result()

        except asyncio.TimeoutError:
            log.warn(f"hook_timeout: cmd={command} timeout={timeout}s")
            return HookResult.continue_result()

        except Exception as e:
            log.error(f"hook_exec_error: cmd={command} error={e}")
            return HookResult.continue_result()
