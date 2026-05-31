import asyncio
from datetime import datetime

from app.agents.context import ContextAssembler, assemble_planner_context
from app.agents.trip_planner_agent import build_travel_planner_graph
from app.schemas.graph import ContextConfig, ContextPacket, ContextProfile, PromptTemplateSpec, TravelPlanState
from app.schemas.trip import TripPlanRequest, TripPreferencesInput


def make_request() -> TripPlanRequest:
    return TripPlanRequest(
        user_id="user-001",
        session_id="session-context-001",
        cities=["Beijing"],
        start_date="2026-06-10",
        end_date="2026-06-12",
        preferences=TripPreferencesInput(
            transport_preference=0,
            accommodation_preference=[0],
            attraction_preference=[0, 1],
        ),
        budget=3000,
        extra_requirements="Keep the pace relaxed",
    )


def packet(
    content: str,
    source: str,
    token_count: int,
    relevance: float,
    recency: float = 0.5,
    importance: float = 0.5,
    confidence: float = 0.5,
) -> ContextPacket:
    return ContextPacket(
        content=content,
        timestamp=datetime(2026, 6, 1),
        token_count=token_count,
        relevance_score=relevance,
        recency_score=recency,
        importance=importance,
        confidence=confidence,
        source=source,
    )


def test_context_assembler_filters_sources_sorts_by_score_and_respects_budget() -> None:
    assembler = ContextAssembler(
        config=ContextConfig(max_tokens=10, reserve_ratio=0, min_relevance=0.2, enable_compression=False)
    )
    profile = ContextProfile(
        profile_name="global_planner",
        max_tokens=10,
        allowed_sources=["semantic", "tool"],
        required_sections=["Known User Preferences", "Tool Observations"],
    )
    prompt = PromptTemplateSpec(
        template_name="planner",
        role="planner",
        task="build plan",
        output_schema_name="TripPlan",
    )
    state: TravelPlanState = {
        "request": make_request(),
        "context_packets": [
            packet("low value semantic", "semantic", 5, relevance=0.3),
            packet("best tool result", "tool", 6, relevance=0.9, importance=0.9),
            packet("blocked hotel", "episodic", 3, relevance=1.0),
            packet("irrelevant semantic", "semantic", 1, relevance=0.1),
        ],
    }

    result = assembler.assemble(state, profile=profile, prompt_template=prompt)

    assert [item.content for item in result.selected_packets] == ["best tool result"]
    assert "blocked hotel" not in result.text
    assert "irrelevant semantic" not in result.text
    assert result.total_tokens == 6
    assert "[Known User Preferences]" in result.text
    assert "[Tool Observations]" in result.text
    assert "[Output Schema]" in result.text
    assert "TripPlan" in result.text


def test_context_assembler_compresses_oversized_packet_when_enabled() -> None:
    assembler = ContextAssembler(
        config=ContextConfig(max_tokens=5, reserve_ratio=0, min_relevance=0, enable_compression=True)
    )
    profile = ContextProfile(profile_name="global_planner", max_tokens=5, allowed_sources=["tool"])
    state: TravelPlanState = {
        "request": make_request(),
        "context_packets": [
            packet("one two three four five six seven", "tool", 7, relevance=1.0),
        ],
    }

    result = assembler.assemble(state, profile=profile)

    assert len(result.selected_packets) == 1
    assert result.total_tokens == 5
    assert "one two three four five" in result.text
    assert "seven" not in result.text


def test_context_assembler_does_not_compress_when_disabled() -> None:
    assembler = ContextAssembler(
        config=ContextConfig(max_tokens=5, reserve_ratio=0, min_relevance=0, enable_compression=False)
    )
    profile = ContextProfile(profile_name="global_planner", max_tokens=5, allowed_sources=["tool"])
    state: TravelPlanState = {
        "request": make_request(),
        "context_packets": [
            packet("one two three four five six seven", "tool", 7, relevance=1.0),
        ],
    }

    result = assembler.assemble(state, profile=profile)

    assert result.selected_packets == []
    assert "one two three" not in result.text


def test_context_assembly_node_writes_planner_context_sections() -> None:
    async def run_node() -> TravelPlanState:
        request = make_request()
        return await assemble_planner_context(
            {
                "request": request,
                "normalized_request": None,
                "semantic_memories": ["User prefers relaxed travel."],
                "tool_observations": ["Amap search retained 9 attractions."],
                "validation_errors": ["Need exactly three meals."],
            }
        )

    result = asyncio.run(run_node())

    assert result["context_packets"]
    assert "[User Request]" in result["planner_context"]
    assert "[Known User Preferences]" in result["planner_context"]
    assert "[Tool Observations]" in result["planner_context"]
    assert "[Validation Errors]" in result["planner_context"]
    assert "[Output Schema]" in result["planner_context"]


def test_travel_planner_graph_runs_context_assembly_before_planner() -> None:
    async def run_graph() -> TravelPlanState:
        request = make_request()
        graph = build_travel_planner_graph()
        return await graph.ainvoke({"request": request}, config={"configurable": {"thread_id": request.session_id}})

    result = asyncio.run(run_graph())

    assert "[User Request]" in result["planner_context"]
    assert result["context_packets"]
