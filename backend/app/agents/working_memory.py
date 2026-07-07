"""Short-term working memory helpers for a planning session."""

from __future__ import annotations

from typing import Any

MAX_WORKING_MEMORY_ITEMS = 50


def append_working_message(messages: list[dict[str, Any]] | None, message: dict[str, Any]) -> list[dict[str, Any]]:
    return _latest([*(messages or []), message])


def append_tool_observation(observations: list[Any] | None, observation: Any) -> list[Any]:
    return _latest([*(observations or []), observation])


def extend_tool_observations(observations: list[Any] | None, new_observations: list[Any]) -> list[Any]:
    return _latest([*(observations or []), *new_observations])


def _latest(values: list[Any]) -> list[Any]:
    return values[-MAX_WORKING_MEMORY_ITEMS:]
