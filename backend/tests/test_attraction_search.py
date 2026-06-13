import asyncio
import json

from app.agents.attraction_search import make_attraction_search_node
from app.schemas.domain import Attraction, Location
from app.schemas.graph import AttractionSearchResult, NormalizedTripRequest, TravelPlanState


def llm_response(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


class FakeLLM:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.messages: list[list[dict]] = []

    async def complete(self, messages: list[dict], **_: object) -> dict:
        self.messages.append(messages)
        return self.responses.pop(0)


class FakeAmap:
    def __init__(self, responses: list[list[Attraction]]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    async def search_attractions(self, keywords: str, city: str | None = None) -> list[Attraction]:
        self.calls.append((keywords, city or ""))
        return self.responses.pop(0)


def normalized_request() -> NormalizedTripRequest:
    return NormalizedTripRequest(
        user_id="user-001",
        cities=["Beijing"],
        start_date="2026-06-10",
        end_date="2026-06-12",
        days_count=3,
        transport_preference="public_transport",
        accommodation_preferences=["hotel"],
        attraction_preferences=["history_culture"],
        budget=3000,
        extra_requirements="Keep the pace relaxed",
        session_id="session-001",
    )


def state() -> TravelPlanState:
    return {
        "normalized_request": normalized_request(),
        "semantic_memories": ["User likes museums."],
        "episodic_memories": [],
        "tool_observations": [],
    }


def test_attraction_search_uses_llm_plan_and_action_to_call_amap() -> None:
    llm = FakeLLM(
        [
            llm_response(
                {
                    "steps": [
                        {
                            "city": "Beijing",
                            "intent": "history culture",
                            "suggested_keywords": ["故宫"],
                        }
                    ]
                }
            ),
            llm_response(
                {
                    "tool_name": "search_attractions",
                    "keywords": "故宫",
                    "city": "北京",
                    "rationale": "Search a major historical attraction first.",
                }
            ),
        ]
    )
    amap = FakeAmap(
        [
            [
                Attraction(
                    name=f"故宫博物院 {index}",
                    city="北京市",
                    poi_id=f"POI-{index}",
                    rating=4.8,
                    location=Location(longitude=116.397128, latitude=39.916527),
                )
                for index in range(6)
            ]
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_attraction_search_node(amap_client=amap, llm_service=llm, max_retries=0)
        return await node(state())

    result = asyncio.run(run_node())

    search_result = AttractionSearchResult.model_validate(result["attraction_search_result"])
    assert amap.calls == [("故宫", "北京")]
    assert search_result.attractions[0].name == "故宫博物院 0"
    assert result["attractions"] == search_result.attractions
    assert search_result.search_keywords == ["故宫"]
    assert search_result.quality is not None
    assert search_result.quality.enough_results is True
    assert any("LLM action search_attractions" in observation for observation in result["tool_observations"])


def test_attraction_search_deduplicates_and_ranks_map_ready_candidates() -> None:
    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "intent": "mixed", "suggested_keywords": ["景点"]}]}),
            llm_response(
                {
                    "tool_name": "search_attractions",
                    "keywords": "景点",
                    "city": "北京",
                    "rationale": "Search general attractions.",
                }
            ),
        ]
    )
    amap = FakeAmap(
        [
            [
                Attraction(name="No Coordinate", city="北京市", poi_id="POI-2", rating=4.9),
                Attraction(
                    name="Map Ready",
                    city="北京市",
                    poi_id="POI-1",
                    rating=4.3,
                    location=Location(longitude=116.3, latitude=39.9),
                ),
                Attraction(
                    name="Map Ready Duplicate",
                    city="北京市",
                    poi_id="POI-1",
                    rating=4.8,
                    location=Location(longitude=116.3, latitude=39.9),
                ),
            ]
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_attraction_search_node(amap_client=amap, llm_service=llm, max_retries=0)
        return await node(state())

    result = asyncio.run(run_node())
    attractions = result["attractions"]

    assert [item.poi_id for item in attractions] == ["POI-1", "POI-2"]
    assert attractions[0].location is not None


def test_attraction_search_retries_with_observation_in_llm_context() -> None:
    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "intent": "history", "suggested_keywords": ["古迹"]}]}),
            llm_response(
                {
                    "tool_name": "search_attractions",
                    "keywords": "不存在的关键词",
                    "city": "北京",
                    "rationale": "Try the first keyword.",
                }
            ),
            llm_response(
                {
                    "tool_name": "search_attractions",
                    "keywords": "博物馆",
                    "city": "北京",
                    "rationale": "Use a broader museum keyword after sparse results.",
                }
            ),
        ]
    )
    amap = FakeAmap(
        [
            [],
            [
                Attraction(
                    name="中国国家博物馆",
                    city="北京市",
                    poi_id="POI-3",
                    location=Location(longitude=116.407, latitude=39.904),
                )
            ],
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_attraction_search_node(amap_client=amap, llm_service=llm, max_retries=1)
        return await node(state())

    result = asyncio.run(run_node())
    second_action_prompt = "\n".join(message["content"] for message in llm.messages[2])

    assert amap.calls == [("不存在的关键词", "北京"), ("博物馆", "北京")]
    assert "quality warning" in second_action_prompt
    assert "returned 0 candidates" in second_action_prompt
    assert result["attractions"][0].name == "中国国家博物馆"


def test_attraction_search_returns_best_effort_after_retry_limit() -> None:
    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "intent": "history", "suggested_keywords": ["古迹"]}]}),
            llm_response(
                {
                    "tool_name": "search_attractions",
                    "keywords": "古迹",
                    "city": "北京",
                    "rationale": "Try historical sites.",
                }
            ),
            llm_response(
                {
                    "tool_name": "search_attractions",
                    "keywords": "博物馆",
                    "city": "北京",
                    "rationale": "Try museums.",
                }
            ),
        ]
    )
    amap = FakeAmap([[], []])

    async def run_node() -> TravelPlanState:
        node = make_attraction_search_node(amap_client=amap, llm_service=llm, max_retries=1)
        return await node(state())

    result = asyncio.run(run_node())
    search_result = result["attraction_search_result"]

    assert search_result.attractions == []
    assert search_result.quality is not None
    assert search_result.quality.enough_results is False
    assert any("Attraction search quality warning" in observation for observation in result["tool_observations"])


def test_attraction_search_falls_back_when_llm_output_is_invalid() -> None:
    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "intent": "history", "suggested_keywords": ["古迹"]}]}),
            llm_response({"tool_name": "maps_weather", "keywords": "", "city": "北京", "rationale": "bad"}),
        ]
    )
    amap = FakeAmap([])

    async def run_node() -> TravelPlanState:
        node = make_attraction_search_node(amap_client=amap, llm_service=llm, max_retries=0)
        return await node(state())

    result = asyncio.run(run_node())

    assert result["attractions"] == []
    assert any("Attraction search LLM action failed" in observation for observation in result["tool_observations"])


def test_attraction_search_skips_when_dependency_is_missing() -> None:
    async def run_node() -> TravelPlanState:
        node = make_attraction_search_node(amap_client=None, llm_service=FakeLLM([]))
        return await node(state())

    result = asyncio.run(run_node())

    assert result["attractions"] == []
    assert result["attraction_search_result"].attractions == []
    assert "Attraction search skipped because amap_client or llm_service is unavailable." in result[
        "tool_observations"
    ]


def test_attraction_search_uses_local_context_builder_for_plan_and_action_messages() -> None:
    class RecordingContextBuilder:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def build_messages(self, *, purpose, state, local_state, output_schema_name, instruction):
            self.calls.append((purpose, local_state))
            return [
                {"role": "system", "content": f"{purpose}:{output_schema_name}"},
                {"role": "user", "content": instruction},
            ]

    builder = RecordingContextBuilder()
    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "intent": "history", "suggested_keywords": ["古迹"]}]}),
            llm_response(
                {
                    "tool_name": "search_attractions",
                    "keywords": "古迹",
                    "city": "北京",
                    "rationale": "Search historic attractions.",
                }
            ),
        ]
    )
    amap = FakeAmap(
        [
            [
                Attraction(
                    name=f"Historic Attraction {index}",
                    city="北京市",
                    poi_id=f"POI-{index}",
                    location=Location(longitude=116.3 + index * 0.001, latitude=39.9),
                )
                for index in range(6)
            ]
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_attraction_search_node(
            amap_client=amap,
            llm_service=llm,
            context_builder=builder,
            max_retries=0,
        )
        return await node(state())

    result = asyncio.run(run_node())

    assert [call[0] for call in builder.calls] == ["attraction_search_plan", "attraction_search_action"]
    assert builder.calls[0][1] is None
    assert builder.calls[1][1].local_plan.steps[0].suggested_keywords == ["古迹"]
    assert llm.messages[0][0]["content"] == "attraction_search_plan:AttractionSearchPlan"
    assert llm.messages[1][0]["content"] == "attraction_search_action:AttractionSearchAction"
    assert len(result["attractions"]) == 6
