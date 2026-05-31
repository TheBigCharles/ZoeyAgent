"""LLM service and reusable LLM node infrastructure."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.errors import PLAN_VALIDATION_FAILED, StructuredAppError, exception_details
from app.core.config import Settings
from app.schemas.graph import PromptTemplateSpec


StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


def dump_openai_response(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    raise TypeError(f"Unsupported LLM response type: {type(response).__name__}")


def validate_structured_output(payload: Any, output_schema: type[StructuredOutput]) -> StructuredOutput:
    if isinstance(payload, output_schema):
        return payload

    data = dump_openai_response(payload) if not isinstance(payload, dict) else payload
    if "choices" in data:
        try:
            message = data["choices"][0]["message"]
            content = message.get("content")
        except (KeyError, IndexError, TypeError) as exc:
            raise StructuredAppError(
                code=PLAN_VALIDATION_FAILED,
                message="LLM response did not contain message content",
                details=exception_details(exc),
            ) from exc

        if isinstance(content, str):
            try:
                data = json.loads(content)
            except json.JSONDecodeError as exc:
                raise StructuredAppError(
                    code=PLAN_VALIDATION_FAILED,
                    message="LLM response content was not valid JSON",
                    details=exception_details(exc),
                ) from exc
        elif isinstance(content, dict):
            data = content
        else:
            raise StructuredAppError(
                code=PLAN_VALIDATION_FAILED,
                message="LLM response content was empty or unsupported",
                details={"content_type": type(content).__name__},
            )

    try:
        return output_schema.model_validate(data)
    except Exception as exc:
        raise StructuredAppError(
            code=PLAN_VALIDATION_FAILED,
            message="LLM structured output validation failed",
            details=exception_details(exc),
        ) from exc


@dataclass(slots=True)
class LLMService:
    settings: Settings
    client: Any | None = None

    async def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        """Run a non-streaming OpenAI-compatible chat completion."""
        response = await self._client().chat.completions.create(
            model=kwargs.pop("model", self.settings.llm_model),
            messages=messages,
            temperature=kwargs.pop("temperature", 0),
            stream=False,
            **kwargs,
        )
        return dump_openai_response(response)

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a non-streaming OpenAI-compatible tool-calling request."""
        response = await self._client().chat.completions.create(
            model=kwargs.pop("model", self.settings.llm_model),
            messages=messages,
            temperature=kwargs.pop("temperature", 0),
            stream=False,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )
        return dump_openai_response(response)

    async def stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Streaming is intentionally deferred until a progress API consumes it."""
        raise NotImplementedError("Streaming LLM responses are deferred for the current MVP step.")
        if False:
            yield {}

    async def call_with_functions(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a function-calling or tool-calling LLM request."""
        return await self.complete_with_tools(messages=messages, tools=tools, **kwargs)

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        if not self.settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY is required before calling LLMService")

        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_base_url,
        )
        return self.client


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 1

    async def run(self, operation):
        last_error: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                return await operation()
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("RetryPolicy requires at least one attempt")


class PromptTemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplateSpec] = {}

    def register(self, spec: PromptTemplateSpec) -> None:
        self._templates[spec.template_name] = spec

    def get(self, template_name: str) -> PromptTemplateSpec:
        try:
            return self._templates[template_name]
        except KeyError as exc:
            raise KeyError(f"Prompt template is not registered: {template_name}") from exc

    def render(self, template_name: str, values: dict[str, Any]) -> list[dict[str, str]]:
        spec = self.get(template_name)
        missing_fields = [field for field in spec.input_fields if field not in values]
        if missing_fields:
            raise ValueError(f"Missing prompt input fields: {', '.join(missing_fields)}")

        return [
            {"role": "system", "content": spec.role.format(**values)},
            {"role": "user", "content": spec.task.format(**values)},
        ]


@dataclass(slots=True)
class BaseLLMNode:
    node_name: str
    llm_service: Any
    prompt_registry: PromptTemplateRegistry
    prompt_template: str
    output_schema: type[StructuredOutput]
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    async def run(self, values: dict[str, Any], **completion_kwargs: Any) -> StructuredOutput:
        messages = self.prompt_registry.render(self.prompt_template, values)

        async def operation() -> dict[str, Any]:
            return await self.llm_service.complete(messages, **completion_kwargs)

        response = await self.retry_policy.run(operation)
        return validate_structured_output(response, self.output_schema)
