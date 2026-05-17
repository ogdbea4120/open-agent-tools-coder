"""
Question tool for asking the user questions during execution.

Provides two tools for user interaction:

- :class:`QuestionTool` — Ask one or more structured questions with options.
- :class:`AskUserTool` — Ask a single simple yes/no or choice question.

Both tools publish events to the event bus so the UI can display questions
and collect responses.
"""

from __future__ import annotations

from typing import Any

from oats.tool.registry import Tool, ToolContext, ToolResult
from oats.core.bus import bus, Event, EventType
from oats.log import cl

log = cl('tool.question')


class QuestionTool(Tool):
    """Ask the user one or more questions and get their response.

    Publishes questions to the event bus so the UI can display them.
    Supports multiple-choice questions with optional multi-select.
    In CLI mode, questions are formatted for terminal display.

    Example:
        ::

            question questions=[{"question": "Which approach?", "header": "Approach",
                         "options": [{"label": "A", "description": "Option A"},
                                     {"label": "B", "description": "Option B"}]}]
    """

    @property
    def name(self) -> str:
        return "question"

    @property
    def description(self) -> str:
        return """Ask the user a question during execution.

Use this to:
- Gather user preferences or requirements
- Clarify ambiguous instructions
- Get decisions on implementation choices
- Offer choices about what direction to take

The user will be presented with the question and options.
They can select from the provided options or type a custom response."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "description": "Questions to ask the user (1-4 questions)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The question to ask",
                            },
                            "header": {
                                "type": "string",
                                "description": "Short label for the question (max 12 chars)",
                            },
                            "options": {
                                "type": "array",
                                "description": "Available choices (2-4 options)",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {
                                            "type": "string",
                                            "description": "Option label (1-5 words)",
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": "Explanation of the option",
                                        },
                                    },
                                    "required": ["label", "description"],
                                },
                            },
                            "multiSelect": {
                                "type": "boolean",
                                "description": "Allow multiple selections",
                                "default": False,
                            },
                        },
                        "required": ["question", "header", "options"],
                    },
                    "minItems": 1,
                    "maxItems": 4,
                },
            },
            "required": ["questions"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Publish one or more questions to the user and await a response.

        Sends a PERMISSION_REQUEST event to the bus so the UI can display the
        questions. In CLI mode, the questions are formatted for display.

        Args:
            args: Must contain ``questions`` — a list of dicts with keys
                ``question``, ``header``, ``options``, and optional ``multiSelect``.
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the formatted questions and a flag indicating
            that a response is awaited.
        """
        questions = args.get("questions", [])

        if not questions:
            return ToolResult(
                title="Question",
                output="",
                error="No questions provided",
            )

        # In a full implementation, this would:
        # 1. Publish an event to the UI to display the question
        # 2. Wait for the user's response
        # 3. Return the response
        #
        # For CLI mode, we'll use a simplified approach where questions
        # are displayed and we wait for input

        # Publish question event for UI handling
        await bus.publish(
            Event(
                type=EventType.PERMISSION_REQUEST,  # Reuse permission event type
                data={
                    "type": "question",
                    "session_id": ctx.session_id,
                    "questions": questions,
                },
            )
        )

        # Format questions for output
        output_lines = ["Questions for user:\n"]

        for i, q in enumerate(questions, 1):
            question_text = q.get("question", "")
            header = q.get("header", "")
            options = q.get("options", [])
            multi = q.get("multiSelect", False)

            output_lines.append(f"{i}. [{header}] {question_text}")
            if multi:
                output_lines.append("   (Multiple selections allowed)")

            for j, opt in enumerate(options, 1):
                label = opt.get("label", "")
                desc = opt.get("description", "")
                output_lines.append(f"   {chr(96+j)}) {label}")
                if desc:
                    output_lines.append(f"      {desc}")

            output_lines.append("")

        output_lines.append("Waiting for user response...")

        # Note: In a real implementation, this would block until
        # the user provides an answer. For now, we return the
        # formatted questions and the processor will need to
        # handle getting the actual response.

        return ToolResult(
            title="Question",
            output="\n".join(output_lines),
            metadata={
                "type": "question",
                "session_id": ctx.session_id,
                "questions": questions,
                "awaiting_response": True,
            },
        )


class AskUserTool(Tool):
    """Simplified tool for asking a single yes/no or choice question.

    Publishes a PERMISSION_REQUEST event to the event bus so the UI can
    display the question and collect a response. Supports optional
    multiple-choice options and a default value.

    Example:
        ::

            ask_user question="Should I proceed with the deletion?"
            ask_user question="Which color?" options=["red", "blue", "green"]
    """

    @property
    def name(self) -> str:
        return "ask_user"

    @property
    def description(self) -> str:
        return """Ask the user a simple yes/no or choice question.

Use for quick confirmations or simple choices.
For complex multi-part questions, use the 'question' tool instead."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask",
                },
                "options": {
                    "type": "array",
                    "description": "Available options (if not provided, expects free text)",
                    "items": {"type": "string"},
                },
                "default": {
                    "type": "string",
                    "description": "Default option if user doesn't respond",
                },
            },
            "required": ["question"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Ask the user a simple question with optional choices.

        Publishes a PERMISSION_REQUEST event to the bus so the UI can display
        the question and collect a response.

        Args:
            args: Must contain ``question`` (str). May contain ``options``
                (list of str) and ``default`` (str).
            ctx: The tool execution context.

        Returns:
            A :class:`ToolResult` with the formatted question and a flag indicating
            that a response is awaited.
        """
        question = args.get("question", "")
        options = args.get("options", [])
        default = args.get("default", "")

        if not question:
            return ToolResult(
                title="AskUser",
                output="",
                error="No question provided",
            )

        # Format the question
        output_lines = [f"Question: {question}"]

        if options:
            output_lines.append("\nOptions:")
            for i, opt in enumerate(options, 1):
                marker = "*" if opt == default else " "
                output_lines.append(f"  {marker}{i}. {opt}")
            if default:
                output_lines.append(f"\nDefault: {default}")
        else:
            output_lines.append("\n(Awaiting free text response)")
            if default:
                output_lines.append(f"Default: {default}")

        # Publish event for UI
        await bus.publish(
            Event(
                type=EventType.PERMISSION_REQUEST,
                data={
                    "type": "ask_user",
                    "session_id": ctx.session_id,
                    "question": question,
                    "options": options,
                    "default": default,
                },
            )
        )

        return ToolResult(
            title="AskUser",
            output="\n".join(output_lines),
            metadata={
                "question": question,
                "options": options,
                "default": default,
                "awaiting_response": True,
            },
        )
