from app.agents.working_memory import append_tool_observation, append_working_message


def test_working_memory_helpers_keep_latest_50_items() -> None:
    messages = [{"role": "user", "content": f"message {index}"} for index in range(50)]
    updated_messages = append_working_message(messages, {"role": "user", "content": "message 50"})

    observations = [f"observation {index}" for index in range(50)]
    updated_observations = append_tool_observation(observations, "observation 50")

    assert len(updated_messages) == 50
    assert updated_messages[0]["content"] == "message 1"
    assert updated_messages[-1]["content"] == "message 50"
    assert len(updated_observations) == 50
    assert updated_observations[0] == "observation 1"
    assert updated_observations[-1] == "observation 50"
