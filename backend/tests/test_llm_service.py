import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from app.services.llm_service import (
    BaseLLMNode,
    LLMService,
    PromptTemplateRegistry,
    RetryPolicy,
    validate_structured_output,
)
from app.config import Settings
from app.schemas.graph import PromptTemplateSpec


class FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return self.payload


class FakeCompletions:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return self.response


class FakeChat:
    def __init__(self, completions: FakeCompletions):
        self.completions = completions


class FakeClient:
    def __init__(self, response: FakeResponse):
        self.completions = FakeCompletions(response)
        self.chat = FakeChat(self.completions)


def make_settings() -> Settings:
    return Settings(LLM_API_KEY="test-key", LLM_BASE_URL="http://llm.test/v1", LLM_MODEL="test-model")


def test_complete_calls_openai_compatible_chat_completion_without_stream() -> None:
    response = FakeResponse({"choices": [{"message": {"content": "hello"}}]})
    client = FakeClient(response)
    service = LLMService(settings=make_settings(), client=client)

    result = asyncio.run(service.complete([{"role": "user", "content": "Hi"}], temperature=0.1))

    assert result == response.payload
    assert client.completions.calls == [
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hi"}],
            "temperature": 0.1,
            "stream": False,
        }
    ]


def test_complete_with_tools_calls_openai_compatible_tool_calling_without_stream() -> None:
    response = FakeResponse({"choices": [{"message": {"tool_calls": []}}]})
    client = FakeClient(response)
    service = LLMService(settings=make_settings(), client=client)
    tools = [{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}]

    result = asyncio.run(service.complete_with_tools([{"role": "user", "content": "Search"}], tools=tools))

    assert result == response.payload
    assert client.completions.calls[0]["tools"] == tools
    assert client.completions.calls[0]["tool_choice"] == "auto"
    assert client.completions.calls[0]["stream"] is False


def test_stream_method_is_explicitly_deferred() -> None:
    service = LLMService(settings=make_settings(), client=FakeClient(FakeResponse({})))

    async def consume_stream() -> None:
        async for _ in service.stream([{"role": "user", "content": "Hi"}]):
            pass

    with pytest.raises(NotImplementedError, match="deferred"):
        asyncio.run(consume_stream())


class PlannerOutput(BaseModel):
    summary: str


def test_validate_structured_output_extracts_message_json_content() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": '{"summary": "valid"}',
                }
            }
        ]
    }

    output = validate_structured_output(response, PlannerOutput)

    assert output == PlannerOutput(summary="valid")


def test_base_llm_node_renders_prompt_retries_and_validates_output() -> None:
    class FlakyLLM:
        def __init__(self) -> None:
            self.calls = 0
            self.messages: list[list[dict[str, str]]] = []

        async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            self.messages.append(messages)
            if self.calls == 1:
                raise RuntimeError("temporary failure")
            return {"choices": [{"message": {"content": '{"summary": "planned"}'}}]}

    registry = PromptTemplateRegistry()
    registry.register(
        PromptTemplateSpec(
            template_name="planner",
            role="You are a planner.",
            task="Plan for {city}.",
            input_fields=["city"],
            allowed_tools=[],
            output_schema_name="PlannerOutput",
        )
    )
    llm = FlakyLLM()
    node = BaseLLMNode(
        node_name="PlannerNode",
        llm_service=llm,
        prompt_registry=registry,
        prompt_template="planner",
        output_schema=PlannerOutput,
        retry_policy=RetryPolicy(max_attempts=2),
    )

    output = asyncio.run(node.run({"city": "Beijing"}))

    assert output == PlannerOutput(summary="planned")
    assert llm.calls == 2
    assert llm.messages[0] == [
        {"role": "system", "content": "You are a planner."},
        {"role": "user", "content": "Plan for Beijing."},
    ]
