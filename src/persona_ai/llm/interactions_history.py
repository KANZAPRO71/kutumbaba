"""Build Interactions API input from Persona-managed session history."""

from __future__ import annotations

from typing import Any

from persona_ai.core.types import Message

HISTORY_WINDOW = 6


def text_content(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def user_input_step(text: str) -> dict[str, Any]:
    return {"type": "user_input", "content": [text_content(text)]}


def model_output_step(text: str) -> dict[str, Any]:
    return {"type": "model_output", "content": [text_content(text)]}


def message_to_step(message: Message) -> dict[str, Any] | None:
    role = message.role.lower()
    if role == "user":
        return user_input_step(message.text)
    if role == "assistant":
        return model_output_step(message.text)
    return None


def build_interactions_input(
    history: list[Message],
    user_message: str,
    *,
    window: int = HISTORY_WINDOW,
) -> list[dict[str, Any]]:
    """Stateless Interactions input — full step timeline for store=False."""
    steps: list[dict[str, Any]] = []
    for message in history[-window:]:
        step = message_to_step(message)
        if step is not None:
            steps.append(step)
    steps.append(user_input_step(user_message))
    return steps
