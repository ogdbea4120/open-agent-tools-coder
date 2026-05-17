"""
TodoWrite tool for task management.

Provides :class:`TodoWriteTool` and :class:`TodoReadTool` for creating,
managing, and reading structured task lists. Tasks are persisted to
session-scoped storage via :class:`KeyValueStorage`.

Data models:

- :class:`TodoItem` — A single task item with content, status, and active form.
- :class:`TodoList` — A list of :class:`TodoItem` objects.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field
from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.core.storage import KeyValueStorage
from oats.log import cl

log = cl('tool.todo')


class TodoItem(BaseModel):
    """A single task item in the todo list.

    Attributes:
        content: The task description in imperative form.
        status: Current status — ``pending``, ``in_progress``, or ``completed``.
        active_form: Present tense description of what is being done
            (e.g., "Implementing feature").
    """

    content: str
    status: Literal["pending", "in_progress", "completed"]
    active_form: str = ""  # Present tense description (e.g., "Implementing feature")


class TodoList(BaseModel):
    """List of todo items for a session.

    Attributes:
        items: The list of :class:`TodoItem` objects.
    """

    items: list[TodoItem] = Field(default_factory=list)


# Global todo storage per session
_todo_storage = KeyValueStorage("todos")


class TodoWriteTool(Tool):
    """Create and manage a structured task list for tracking progress.

    Persists todo items to session-scoped storage. Supports three statuses:
    ``pending``, ``in_progress``, and ``completed``. Each item has a
    description (``content``) and a present-tense active form.

    Example:
        ::

            todowrite todos=[
                {"content": "Implement auth", "status": "in_progress", "activeForm": "Implementing auth"},
                {"content": "Write tests", "status": "pending", "activeForm": "Writing tests"}
            ]
    """

    @property
    def name(self) -> str:
        return "todowrite"

    @property
    def description(self) -> str:
        return """Create and manage a structured task list for tracking progress.

Use this tool to:
- Plan complex multi-step tasks
- Track progress on implementation
- Break down large tasks into smaller steps
- Show the user what you're working on

Guidelines:
- Use for tasks with 3+ steps
- Mark tasks in_progress BEFORE starting work
- Mark tasks completed IMMEDIATELY after finishing
- Only have ONE task in_progress at a time
- Each todo needs both 'content' (what to do) and 'activeForm' (what you're doing)

Example:
  content: "Implement user authentication"
  activeForm: "Implementing user authentication"
  status: "in_progress"
"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The updated todo list",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "The task description (imperative form)",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Task status",
                            },
                            "activeForm": {
                                "type": "string",
                                "description": "Present continuous form (e.g., 'Implementing feature')",
                            },
                        },
                        "required": ["content", "status", "activeForm"],
                    },
                },
            },
            "required": ["todos"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Store the updated todo list for the current session.

        Parses the incoming todo items, validates them, persists them to
        session-scoped storage, and returns a formatted summary.

        Args:
            args: Must contain ``todos`` — a list of dicts with keys
                ``content``, ``status``, and ``activeForm``.
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the formatted todo list and progress summary.
        """
        todos_data = args.get("todos", [])

        if not todos_data:
            return ToolResult(
                title="TodoWrite",
                output="Todo list cleared.",
                metadata={"session_id": ctx.session_id, "count": 0},
            )

        # Parse and validate todos
        items: list[TodoItem] = []
        for item in todos_data:
            items.append(
                TodoItem(
                    content=item.get("content", ""),
                    status=item.get("status", "pending"),
                    active_form=item.get("activeForm", ""),
                )
            )

        # Store the todo list
        todo_list = TodoList(items=items)
        await _todo_storage.set(ctx.session_id, todo_list.model_dump())

        # Format output
        output_lines = ["Todo list updated:\n"]
        for i, item in enumerate(items, 1):
            status_icon = {
                "pending": "○",
                "in_progress": "◐",
                "completed": "●",
            }.get(item.status, "○")

            output_lines.append(f"{i}. [{status_icon}] {item.content}")
            if item.status == "in_progress" and item.active_form:
                output_lines.append(f"   → {item.active_form}")

        # Summary
        pending = sum(1 for t in items if t.status == "pending")
        in_progress = sum(1 for t in items if t.status == "in_progress")
        completed = sum(1 for t in items if t.status == "completed")
        output_lines.append(f"\nProgress: {completed}/{len(items)} completed")
        if in_progress > 0:
            output_lines.append(f"Currently: {in_progress} in progress")

        return ToolResult(
            title="TodoWrite",
            output="\n".join(output_lines),
            metadata={
                "session_id": ctx.session_id,
                "count": len(items),
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
            },
        )


class TodoReadTool(Tool):
    """Read and display the current task list for the session.

    Loads the persisted todo list from session-scoped storage and formats
    it with status icons and a progress summary.

    Example:
        ::

            toread
    """

    @property
    def name(self) -> str:
        return "todoread"

    @property
    def description(self) -> str:
        return """Read the current todo list for this session.

Returns the list of tasks with their status."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Read and display the current todo list for the session.

        Retrieves the stored todo list from session-scoped storage and formats
        it with status icons and a progress summary.

        Args:
            args: Unused (no parameters required).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the formatted todo list and progress summary.
        """
        data = await _todo_storage.get(ctx.session_id)

        if not data:
            return ToolResult(
                title="TodoRead",
                output="No todos found for this session.",
                metadata={"session_id": ctx.session_id, "count": 0},
            )

        todo_list = TodoList.model_validate(data)
        items = todo_list.items

        if not items:
            return ToolResult(
                title="TodoRead",
                output="Todo list is empty.",
                metadata={"session_id": ctx.session_id, "count": 0},
            )

        # Format output
        output_lines = ["Current todos:\n"]
        for i, item in enumerate(items, 1):
            status_icon = {
                "pending": "○",
                "in_progress": "◐",
                "completed": "●",
            }.get(item.status, "○")

            output_lines.append(f"{i}. [{status_icon}] {item.content}")
            if item.status == "in_progress" and item.active_form:
                output_lines.append(f"   → {item.active_form}")

        # Summary
        pending = sum(1 for t in items if t.status == "pending")
        in_progress = sum(1 for t in items if t.status == "in_progress")
        completed = sum(1 for t in items if t.status == "completed")
        output_lines.append(f"\nProgress: {completed}/{len(items)} completed")

        return ToolResult(
            title="TodoRead",
            output="\n".join(output_lines),
            metadata={
                "session_id": ctx.session_id,
                "count": len(items),
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
            },
        )
