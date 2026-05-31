"""LLM API service boundary.

The implementation should wrap OpenAI-compatible chat completions, structured
outputs, function calling, and streaming responses behind this module.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


@dataclass(slots=True)
class LLMService:
    settings: Settings

    async def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        """Run a non-streaming OpenAI-compatible chat completion."""
        raise NotImplementedError

    async def stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Run a streaming OpenAI-compatible chat completion."""
        raise NotImplementedError
        yield {}

    async def call_with_functions(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a function-calling or tool-calling LLM request."""
        raise NotImplementedError
