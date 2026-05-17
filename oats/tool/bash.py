"""
Bash tool for executing shell commands.

Provides :class:`BashTool` which runs shell commands in a subprocess with
configurable timeout and working directory. Output is captured and truncated
if it exceeds configured limits. AWS commands are automatically classified
and redacted for safety via :mod:`oats.tool.aws_safety`.
"""
from __future__ import annotations


import asyncio
from pathlib import Path
from typing import Any
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.log import cl

log = cl('tool.bash')

class BashTool(Tool):
    """Execute shell commands in a subprocess.

    Runs bash commands with configurable timeout and working directory.
    Output is captured and truncated if it exceeds configured limits.
    AWS commands are automatically classified and redacted for safety.

    Example:
        ::

            bash command="pip install requests"
            bash command="pytest tests/" timeout=60
    """

    MAX_OUTPUT_LINES = 5000
    MAX_OUTPUT_BYTES = 1000000000
    DEFAULT_TIMEOUT = 300  # seconds

    @property
    def name(self) -> str:
        return "bash"

    @property
    def aliases(self) -> list[str]:
        return ["shell", "terminal", "command"]

    @property
    def keywords(self) -> list[str]:
        return [
            "run command",
            "execute shell command",
            "terminal command",
            "build",
            "test",
            "git",
        ]

    @property
    def always_load(self) -> bool:
        return True

    @property
    def strict(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return """Execute a bash command in the shell.

Use this for:
- Running build commands (npm, pip, cargo, etc.)
- Git operations
- Running scripts and tests
- System commands that have no dedicated tool

Do NOT use bash for:
- Reading files: use the `read` tool instead (never cat, head, tail)
- Searching files: use the `grep` tool instead (never grep, rg)
- Finding files: use the `glob` tool instead (never find, ls)
- Editing files: use the `edit` tool instead (never sed, awk)
- Writing files: use the `write` tool instead (never echo >)"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 120, max 600)",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the command (defaults to project dir)",
                },
            },
            "required": ["command"],
        }

    def requires_permission(self, args: dict[str, Any], ctx: ToolContext) -> str | None:
        """Bash commands always require user permission before execution.

        Args:
            args: The tool arguments containing the ``command``.
            ctx: The tool execution context.

        Returns:
            A permission prompt string describing the command to be executed.
        """
        command = args.get("command", "")
        return f"Execute command: {command[:100]}{'...' if len(command) > 100 else ''}"

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute a shell command and capture its output.

        Runs the command in a subprocess with stdout/stderr merged. Output is
        truncated if it exceeds the configured limits.

        Args:
            args: Must contain ``command`` (str). May contain ``timeout`` (int,
                seconds) and ``working_dir`` (str).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the command output and exit code.
        """
        command = args.get("command", "")
        timeout = min(args.get("timeout", self.DEFAULT_TIMEOUT), 600)
        working_dir = args.get("working_dir")

        if not command:
            return ToolResult(
                title="Bash",
                output="",
                error="No command provided",
            )

        # Determine working directory
        cwd = Path(working_dir) if working_dir else ctx.working_dir
        if not cwd.exists():
            return ToolResult(
                title="Bash",
                output="",
                error=f"Working directory does not exist: {cwd}",
            )

        try:
            # Create the subprocess
            log.info(f'bash_running_command:\n{command}\n')
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(cwd),
                env=None,  # Use current environment
            )

            try:
                # Wait for completion with timeout
                stdout, _ = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    title="Bash (timeout)",
                    output=f"Command timed out after {timeout} seconds",
                    metadata={"command": command, "timeout": True, "exit_code": -1},
                    error="Command timed out",
                )

            # Decode output
            output = stdout.decode("utf-8", errors="replace")

            # Truncate if needed
            output, truncated = self._truncate_output(output)

            exit_code = process.returncode

            return ToolResult(
                title=f"Bash (exit {exit_code})",
                output=output,
                metadata={
                    "command": command,
                    "exit_code": exit_code,
                    "truncated": truncated,
                    "working_dir": str(cwd),
                },
                error=None if exit_code == 0 else f"Command exited with code {exit_code}",
            )

        except Exception as e:
            return ToolResult(
                title="Bash (error)",
                output="",
                metadata={"command": command},
                error=str(e),
            )

    def _truncate_output(self, output: str) -> tuple[str, bool]:
        """Truncate command output if it exceeds byte or line limits.

        Enforces MAX_OUTPUT_BYTES (byte limit) and MAX_OUTPUT_LINES (line limit).
        Appends a truncation notice if either limit is hit.

        Args:
            output: The raw command output.

        Returns:
            A tuple of ``(truncated_output, was_truncated)``.
        """
        truncated = False

        # Check byte limit
        if len(output.encode("utf-8")) > self.MAX_OUTPUT_BYTES:
            output = output[: self.MAX_OUTPUT_BYTES]
            truncated = True

        # Check line limit
        lines = output.split("\n")
        if len(lines) > self.MAX_OUTPUT_LINES:
            lines = lines[: self.MAX_OUTPUT_LINES]
            lines.append(f"\n... (truncated, {len(lines)} lines shown)")
            output = "\n".join(lines)
            truncated = True

        if truncated:
            output += "\n[Output truncated]"

        return output, truncated
