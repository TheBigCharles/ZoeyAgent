from app.agents.working_memory import maintain_tool_observations, maintain_working_messages
from app.memory.extraction import MemoryExtractionService
from app.schemas.memory import MemoryCandidate


def test_working_memory_helpers_keep_latest_50_items() -> None:
    messages = [{"role": "user", "content": f"message {index}"} for index in range(50)]
    message_result = maintain_working_messages(messages, {"role": "user", "content": "message 50"})

    observations = [f"observation {index}" for index in range(50)]
    observation_result = maintain_tool_observations(observations, "observation 50")

    assert len(message_result.retained_messages) == 50
    assert message_result.retained_messages[0]["content"] == "message 1"
    assert message_result.retained_messages[-1]["content"] == "message 50"
    assert len(observation_result.retained_messages) == 50
    assert observation_result.retained_messages[0] == "observation 1"
    assert observation_result.retained_messages[-1] == "observation 50"


def test_working_memory_overflow_extracts_candidates_before_dropping_items() -> None:
    messages = [{"role": "user", "content": "我喜欢轻松节奏，不要太赶。"}]
    messages.extend({"role": "user", "content": f"message {index}"} for index in range(50))

    result = maintain_working_messages(
        messages,
        {"role": "user", "content": "latest"},
        extraction_service=MemoryExtractionService(),
    )

    assert len(result.retained_messages) == 50
    assert result.dropped_count == 2
    assert any(candidate.target == "semantic" and "轻松节奏" in candidate.text for candidate in result.extracted_candidates)


def test_working_memory_overflow_deduplicates_against_existing_candidates() -> None:
    messages = [{"role": "user", "content": "我喜欢轻松节奏，不要太赶。"}]
    messages.extend({"role": "user", "content": f"message {index}"} for index in range(50))
    existing = [
        MemoryCandidate(
            target="semantic",
            text="用户偏好轻松节奏",
            reason="existing",
            confidence=0.9,
        )
    ]

    result = maintain_working_messages(
        messages,
        {"role": "user", "content": "latest"},
        extraction_service=MemoryExtractionService(),
        existing_candidates=existing,
    )

    assert result.extracted_candidates == []


def test_tool_observation_overflow_extracts_candidates_before_dropping_items() -> None:
    observations = ["用户选择了王府井附近酒店。"]
    observations.extend(f"observation {index}" for index in range(50))

    result = maintain_tool_observations(
        observations,
        "latest",
        extraction_service=MemoryExtractionService(),
    )

    assert len(result.retained_messages) == 50
    assert result.dropped_count == 2
    assert any(candidate.target == "episodic" and "王府井" in candidate.text for candidate in result.extracted_candidates)
