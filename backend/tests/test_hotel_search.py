import asyncio
import json

from app.agents.hotel_search import make_hotel_search_node
from app.schemas.domain import Attraction, Hotel, Location
from app.schemas.graph import HotelSearchResult, NormalizedTripRequest, TravelPlanState


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
    def __init__(self, responses: list[list[Hotel]]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    async def search_hotels(self, keywords: str, city: str | None = None) -> list[Hotel]:
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
        accommodation_preferences=["budget_hotel"],
        attraction_preferences=["history_culture"],
        budget=3000,
        extra_requirements="Keep the pace relaxed",
        session_id="session-001",
    )


def state() -> TravelPlanState:
    return {
        "normalized_request": normalized_request(),
        "semantic_memories": ["User prefers hotels close to attractions."],
        "episodic_memories": [],
        "tool_observations": [],
        "attractions": [
            Attraction(
                name="故宫博物院",
                city="北京市",
                address="景山前街4号",
                poi_id="A-1",
                location=Location(longitude=116.397128, latitude=39.916527),
            )
        ],
    }


def test_hotel_search_uses_llm_plan_and_action_to_call_amap() -> None:
    llm = FakeLLM(
        [
            llm_response(
                {
                    "steps": [
                        {
                            "city": "Beijing",
                            "anchor": "故宫博物院",
                            "intent": "budget hotel near the main attraction",
                            "suggested_keywords": ["故宫 附近 酒店"],
                        }
                    ]
                }
            ),
            llm_response(
                {
                    "tool_name": "search_hotels",
                    "keywords": "故宫 附近 酒店",
                    "city": "北京",
                    "anchor": "故宫博物院",
                    "rationale": "Search around the selected attraction.",
                }
            ),
        ]
    )
    amap = FakeAmap(
        [
            [
                Hotel(
                    name=f"北京测试酒店 {index}",
                    city="北京市",
                    poi_id=f"HOTEL-{index}",
                    rating=4.6,
                    estimated_cost=500,
                    location=Location(longitude=116.4 + index * 0.001, latitude=39.9),
                )
                for index in range(4)
            ]
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_hotel_search_node(amap_client=amap, llm_service=llm, max_retries=0)
        return await node(state())

    result = asyncio.run(run_node())

    search_result = HotelSearchResult.model_validate(result["hotel_search_result"])
    assert amap.calls == [("故宫 附近 酒店", "北京")]
    assert search_result.selected_hotel is not None
    assert search_result.selected_hotel.name == "北京测试酒店 0"
    assert result["hotels"] == search_result.candidate_hotels
    assert search_result.search_areas == ["故宫博物院"]
    assert search_result.quality is not None
    assert search_result.quality.enough_results is True
    assert any("LLM action search_hotels" in observation for observation in result["tool_observations"])


def test_hotel_search_enriches_route_summary_when_client_supports_it() -> None:
    class RouteAmap(FakeAmap):
        def __init__(self, responses: list[list[Hotel]]):
            super().__init__(responses)
            self.route_calls: list[tuple[str, str, str]] = []

        async def get_route_summary(
            self,
            origin_address: str,
            destination_address: str,
            mode: str,
            origin_city: str | None = None,
            destination_city: str | None = None,
        ) -> dict:
            self.route_calls.append((origin_address, destination_address, mode))
            return {
                "route_distance_km": 2.5,
                "route_duration_minutes": 18,
                "transit_method": mode,
            }

    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "anchor": "故宫", "intent": "hotel", "suggested_keywords": ["酒店"]}]}),
            llm_response(
                {
                    "tool_name": "search_hotels",
                    "keywords": "酒店",
                    "city": "北京",
                    "anchor": "故宫",
                    "rationale": "Search hotels.",
                }
            ),
        ]
    )
    amap = RouteAmap(
        [
            [
                Hotel(
                    name="Route Ready Hotel",
                    city="北京市",
                    address="酒店路1号",
                    poi_id="H-ROUTE",
                    estimated_cost=450,
                    location=Location(longitude=116.4, latitude=39.91),
                )
                for _ in range(4)
            ]
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_hotel_search_node(amap_client=amap, llm_service=llm, max_retries=0)
        return await node(state())

    result = asyncio.run(run_node())
    hotel = result["hotels"][0]

    assert amap.route_calls[0] == ("酒店路1号", "景山前街4号", "transit")
    assert hotel.distance_to_main_area_km == 2.5
    assert hotel.estimated_travel_time_minutes == 18
    assert hotel.transit_method == "transit"


def test_hotel_search_route_summary_timeout_does_not_block_result() -> None:
    class SlowRouteAmap(FakeAmap):
        async def get_route_summary(
            self,
            origin_address: str,
            destination_address: str,
            mode: str,
            origin_city: str | None = None,
            destination_city: str | None = None,
        ) -> dict:
            await asyncio.sleep(0.2)
            return {
                "route_distance_km": 2.5,
                "route_duration_minutes": 18,
                "transit_method": mode,
            }

    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "anchor": "故宫", "intent": "hotel", "suggested_keywords": ["酒店"]}]}),
            llm_response(
                {
                    "tool_name": "search_hotels",
                    "keywords": "酒店",
                    "city": "北京",
                    "anchor": "故宫",
                    "rationale": "Search hotels.",
                }
            ),
        ]
    )
    amap = SlowRouteAmap(
        [
            [
                Hotel(
                    name=f"Slow Route Hotel {index}",
                    city="北京市",
                    address=f"酒店路{index}号",
                    poi_id=f"H-SLOW-{index}",
                    estimated_cost=450,
                    location=Location(longitude=116.4 + index * 0.001, latitude=39.91),
                )
                for index in range(4)
            ]
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_hotel_search_node(
            amap_client=amap,
            llm_service=llm,
            max_retries=0,
            route_summary_timeout_seconds=0.01,
        )
        return await asyncio.wait_for(node(state()), timeout=0.5)

    result = asyncio.run(run_node())

    assert len(result["hotels"]) == 4
    assert result["hotels"][0].distance_to_main_area_km is None
    assert any("Hotel route summary failed" in observation for observation in result["tool_observations"])
    assert result["hotel_search_result"].selected_hotel is not None


def test_hotel_search_deduplicates_and_ranks_map_ready_candidates() -> None:
    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "anchor": "故宫", "intent": "hotel", "suggested_keywords": ["酒店"]}]}),
            llm_response(
                {
                    "tool_name": "search_hotels",
                    "keywords": "酒店",
                    "city": "北京",
                    "anchor": "故宫",
                    "rationale": "Search hotels.",
                }
            ),
        ]
    )
    amap = FakeAmap(
        [
            [
                Hotel(name="No Coordinate", city="北京市", poi_id="H-2", rating=4.9, estimated_cost=300),
                Hotel(
                    name="Map Ready",
                    city="北京市",
                    poi_id="H-1",
                    rating=4.3,
                    estimated_cost=500,
                    location=Location(longitude=116.3, latitude=39.9),
                ),
                Hotel(
                    name="Map Ready Duplicate",
                    city="北京市",
                    poi_id="H-1",
                    rating=4.8,
                    estimated_cost=520,
                    location=Location(longitude=116.3, latitude=39.9),
                ),
            ]
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_hotel_search_node(amap_client=amap, llm_service=llm, max_retries=0)
        return await node(state())

    result = asyncio.run(run_node())
    hotels = result["hotels"]

    assert [item.poi_id for item in hotels] == ["H-1", "H-2"]
    assert hotels[0].location is not None


def test_hotel_search_retries_with_observation_in_llm_context() -> None:
    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "anchor": "故宫", "intent": "budget", "suggested_keywords": ["不存在酒店"]}]}),
            llm_response(
                {
                    "tool_name": "search_hotels",
                    "keywords": "不存在酒店",
                    "city": "北京",
                    "anchor": "故宫",
                    "rationale": "Try first keyword.",
                }
            ),
            llm_response(
                {
                    "tool_name": "search_hotels",
                    "keywords": "经济型酒店",
                    "city": "北京",
                    "anchor": "故宫",
                    "rationale": "Broaden to budget hotels after sparse results.",
                }
            ),
        ]
    )
    amap = FakeAmap(
        [
            [],
            [
                Hotel(
                    name="北京经济酒店",
                    city="北京市",
                    poi_id="H-3",
                    estimated_cost=350,
                    location=Location(longitude=116.407, latitude=39.904),
                )
            ],
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_hotel_search_node(amap_client=amap, llm_service=llm, max_retries=1)
        return await node(state())

    result = asyncio.run(run_node())
    second_action_prompt = "\n".join(message["content"] for message in llm.messages[2])

    assert amap.calls == [("不存在酒店", "北京"), ("经济型酒店", "北京")]
    assert "quality warning" in second_action_prompt
    assert "returned 0 candidates" in second_action_prompt
    assert result["hotels"][0].name == "北京经济酒店"


def test_hotel_search_returns_best_effort_after_retry_limit() -> None:
    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "anchor": "故宫", "intent": "hotel", "suggested_keywords": ["酒店"]}]}),
            llm_response(
                {
                    "tool_name": "search_hotels",
                    "keywords": "酒店",
                    "city": "北京",
                    "anchor": "故宫",
                    "rationale": "Try hotels.",
                }
            ),
        ]
    )
    amap = FakeAmap([[]])

    async def run_node() -> TravelPlanState:
        node = make_hotel_search_node(amap_client=amap, llm_service=llm, max_retries=0)
        return await node(state())

    result = asyncio.run(run_node())
    search_result = result["hotel_search_result"]

    assert search_result.candidate_hotels == []
    assert search_result.selected_hotel is None
    assert search_result.quality is not None
    assert search_result.quality.enough_results is False
    assert any("Hotel search quality warning" in observation for observation in result["tool_observations"])


def test_hotel_search_falls_back_when_llm_output_is_invalid() -> None:
    llm = FakeLLM(
        [
            llm_response({"steps": [{"city": "Beijing", "anchor": "故宫", "intent": "hotel", "suggested_keywords": ["酒店"]}]}),
            llm_response({"tool_name": "maps_weather", "keywords": "", "city": "北京", "anchor": "故宫", "rationale": "bad"}),
        ]
    )
    amap = FakeAmap([])

    async def run_node() -> TravelPlanState:
        node = make_hotel_search_node(amap_client=amap, llm_service=llm, max_retries=0)
        return await node(state())

    result = asyncio.run(run_node())

    assert result["hotels"] == []
    assert any("Hotel search LLM action failed" in observation for observation in result["tool_observations"])


def test_hotel_search_skips_when_dependency_is_missing() -> None:
    async def run_node() -> TravelPlanState:
        node = make_hotel_search_node(amap_client=None, llm_service=FakeLLM([]))
        return await node(state())

    result = asyncio.run(run_node())

    assert result["hotels"] == []
    assert result["hotel_search_result"].candidate_hotels == []
    assert "Hotel search skipped because amap_client or llm_service is unavailable." in result[
        "tool_observations"
    ]


def test_hotel_search_uses_local_context_builder_for_plan_and_action_messages() -> None:
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
            llm_response({"steps": [{"city": "Beijing", "anchor": "故宫", "intent": "hotel", "suggested_keywords": ["酒店"]}]}),
            llm_response(
                {
                    "tool_name": "search_hotels",
                    "keywords": "酒店",
                    "city": "北京",
                    "anchor": "故宫",
                    "rationale": "Search hotels.",
                }
            ),
        ]
    )
    amap = FakeAmap(
        [
            [
                Hotel(
                    name=f"Hotel {index}",
                    city="北京市",
                    poi_id=f"H-{index}",
                    estimated_cost=400,
                    location=Location(longitude=116.3 + index * 0.001, latitude=39.9),
                )
                for index in range(4)
            ]
        ]
    )

    async def run_node() -> TravelPlanState:
        node = make_hotel_search_node(
            amap_client=amap,
            llm_service=llm,
            context_builder=builder,
            max_retries=0,
        )
        return await node(state())

    result = asyncio.run(run_node())

    assert [call[0] for call in builder.calls] == ["hotel_search_plan", "hotel_search_action"]
    assert builder.calls[0][1] is None
    assert builder.calls[1][1].local_plan.steps[0].suggested_keywords == ["酒店"]
    assert llm.messages[0][0]["content"] == "hotel_search_plan:HotelSearchPlan"
    assert llm.messages[1][0]["content"] == "hotel_search_action:HotelSearchAction"
    assert len(result["hotels"]) == 4
