import asyncio
import json
from datetime import date

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.trip_planner_agent import build_travel_planner_graph
from app.agents.nodes import make_weather_query_node
from app.schemas.domain import Attraction, Hotel, Location, WeatherInfo
from app.schemas.graph import TravelPlanState
from app.schemas.trip import TripPlan, TripPlanRequest, TripPreferencesInput


def make_request() -> TripPlanRequest:
    return TripPlanRequest(
        user_id="user-001",
        session_id="session-graph-001",
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


def llm_response(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


class FakeAttractionLLM:
    async def complete(self, messages: list[dict], **_: object) -> dict:
        text = "\n".join(message["content"] for message in messages)
        if "酒店搜索 ReAct executor" in text:
            return llm_response(
                {
                    "tool_name": "search_hotels",
                    "keywords": "budget hotel",
                    "city": "Beijing",
                    "anchor": "Museum 0",
                    "rationale": "Search hotels near the first attraction.",
                }
            )
        if "酒店搜索 plan" in text or "局部酒店搜索 plan" in text:
            return llm_response(
                {
                    "steps": [
                        {
                            "city": "Beijing",
                            "anchor": "Museum 0",
                            "intent": "budget hotel near attractions",
                            "suggested_keywords": ["budget hotel"],
                        }
                    ]
                }
            )
        if "景点搜索 ReAct executor" in text or "选择下一次 action" in text:
            return llm_response(
                {
                    "tool_name": "search_attractions",
                    "keywords": "museum",
                    "city": "Beijing",
                    "rationale": "Search museums for the history preference.",
                }
            )
        if "景点搜索" in text and "局部 plan" in text:
            return llm_response(
                {
                    "steps": [
                        {
                            "city": "Beijing",
                            "intent": "history culture",
                            "suggested_keywords": ["museum"],
                        }
                    ]
                }
            )
        raise AssertionError("unexpected prompt")


def invalid_business_trip_payload() -> dict:
    return {
        "session_id": "session-graph-001",
        "cities": ["Beijing"],
        "start_date": "2026-06-10",
        "end_date": "2026-06-12",
        "days": [
            {
                "date": "2026-06-11",
                "day_index": 0,
                "city": "Beijing",
                "description": "Wrong date for day index.",
                "transportation": "public_transport",
                "accommodation": "budget_hotel",
                "meals": [],
                "total_price": 120,
            },
            {
                "date": "2026-06-11",
                "day_index": 1,
                "city": "Beijing",
                "description": "No map point despite located attraction.",
                "transportation": "public_transport",
                "accommodation": "budget_hotel",
                "attractions": [
                    {
                        "name": "Museum",
                        "city": "Beijing",
                        "location": {"longitude": 116.39, "latitude": 39.9},
                    }
                ],
                "meals": [],
                "map_points": [],
                "total_price": 120,
            },
            {
                "date": "2026-06-12",
                "day_index": 2,
                "city": "Beijing",
                "description": "Valid date.",
                "transportation": "public_transport",
                "accommodation": "budget_hotel",
                "meals": [],
                "total_price": 120,
            },
        ],
        "weather_info": [],
        "overall_suggestions": "Invalid business plan.",
    }


def valid_business_trip_payload() -> dict:
    return {
        "session_id": "session-graph-001",
        "cities": ["Beijing"],
        "start_date": "2026-06-10",
        "end_date": "2026-06-12",
        "days": [
            {
                "date": "2026-06-10",
                "day_index": 0,
                "city": "Beijing",
                "description": "Fixed day 1.",
                "transportation": "public_transport",
                "accommodation": "budget_hotel",
                "meals": [],
                "total_price": 120,
            },
            {
                "date": "2026-06-11",
                "day_index": 1,
                "city": "Beijing",
                "description": "Fixed day 2.",
                "transportation": "public_transport",
                "accommodation": "budget_hotel",
                "attractions": [
                    {
                        "name": "Museum",
                        "city": "Beijing",
                        "location": {"longitude": 116.39, "latitude": 39.9},
                    }
                ],
                "meals": [],
                "map_points": [
                    {
                        "name": "Museum",
                        "city": "Beijing",
                        "location": {"longitude": 116.39, "latitude": 39.9},
                        "day_index": 1,
                        "order_index": 0,
                        "point_type": "attraction",
                    }
                ],
                "total_price": 120,
            },
            {
                "date": "2026-06-12",
                "day_index": 2,
                "city": "Beijing",
                "description": "Fixed day 3.",
                "transportation": "public_transport",
                "accommodation": "budget_hotel",
                "meals": [],
                "total_price": 120,
            },
        ],
        "weather_info": [],
        "overall_suggestions": "Fixed by repair.",
    }


class RepairingPlannerLLM(FakeAttractionLLM):
    def __init__(self) -> None:
        self.planner_calls = 0

    async def complete(self, messages: list[dict], **kwargs: object) -> dict:
        text = "\n".join(message["content"] for message in messages)
        if "你是主旅行规划 PlannerNode" not in text:
            return await super().complete(messages, **kwargs)
        self.planner_calls += 1
        payload = invalid_business_trip_payload() if self.planner_calls == 1 else valid_business_trip_payload()
        return llm_response(payload)


class AlwaysInvalidPlannerLLM(FakeAttractionLLM):
    def __init__(self) -> None:
        self.planner_calls = 0

    async def complete(self, messages: list[dict], **kwargs: object) -> dict:
        text = "\n".join(message["content"] for message in messages)
        if "你是主旅行规划 PlannerNode" not in text:
            return await super().complete(messages, **kwargs)
        self.planner_calls += 1
        return llm_response(invalid_business_trip_payload())


def test_minimal_travel_planner_graph_outputs_valid_trip_plan() -> None:
    async def run_graph() -> TravelPlanState:
        graph = build_travel_planner_graph()
        request = make_request()
        return await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )

    result = asyncio.run(run_graph())

    trip_plan = TripPlan.model_validate(result["trip_plan"])
    assert result["normalized_request"].session_id == "session-graph-001"
    assert trip_plan.session_id == "session-graph-001"
    assert len(trip_plan.days) == 3
    assert trip_plan.overall_suggestions != "Mock trip plan generated by TravelPlannerGraph."
    assert all(len(day.meals) == 3 for day in trip_plan.days)
    assert all(day.total_price >= 0 for day in trip_plan.days)


def test_travel_planner_graph_queries_weather_before_planning() -> None:
    class WeatherClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def get_weather(self, city: str) -> list[WeatherInfo]:
            self.calls.append(city)
            return [
                WeatherInfo(
                    city=city,
                    date=date(2026, 6, 10),
                    day_weather="sunny",
                    night_weather="cloudy",
                    day_temp=28,
                    night_temp=18,
                    wind_direction="east",
                    wind_power="1-3",
                )
            ]

    async def run_graph() -> tuple[TravelPlanState, WeatherClient]:
        client = WeatherClient()
        graph = build_travel_planner_graph(amap_client=client)
        request = make_request()
        result = await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )
        return result, client

    result, client = asyncio.run(run_graph())

    trip_plan = TripPlan.model_validate(result["trip_plan"])
    assert client.calls == ["Beijing"]
    assert len(result["weather_info"]) == 1
    assert trip_plan.weather_info == result["weather_info"]
    assert "Amap weather query for Beijing returned 1 records." in result["tool_observations"]


def test_travel_planner_graph_keeps_planning_when_weather_fails() -> None:
    class FailingWeatherClient:
        async def get_weather(self, city: str) -> list[WeatherInfo]:
            raise RuntimeError("weather unavailable")

    async def run_graph() -> TravelPlanState:
        graph = build_travel_planner_graph(amap_client=FailingWeatherClient())
        request = make_request()
        return await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )

    result = asyncio.run(run_graph())

    trip_plan = TripPlan.model_validate(result["trip_plan"])
    assert trip_plan.weather_info == []
    assert result["weather_info"] == []
    assert "Amap weather query for Beijing failed: RuntimeError." in result["tool_observations"]


def test_travel_planner_graph_writes_attraction_search_result_before_planning() -> None:
    class SearchClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def search_attractions(self, keywords: str, city: str | None = None) -> list[Attraction]:
            self.calls.append(f"{city}:{keywords}")
            return [
                Attraction(
                    name=f"Museum {index}",
                    city=city,
                    poi_id=f"POI-{index}",
                    location=Location(longitude=116.3 + index * 0.001, latitude=39.9),
                    rating=4.5,
                )
                for index in range(6)
            ]

        async def get_weather(self, city: str) -> list[WeatherInfo]:
            return []

    async def run_graph() -> tuple[TravelPlanState, SearchClient]:
        client = SearchClient()
        graph = build_travel_planner_graph(amap_client=client, llm_service=FakeAttractionLLM())
        request = make_request()
        result = await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )
        return result, client

    result, client = asyncio.run(run_graph())

    trip_plan = TripPlan.model_validate(result["trip_plan"])
    assert client.calls == ["Beijing:museum"]
    assert len(result["attraction_search_result"].attractions) == 6
    assert result["attractions"] == result["attraction_search_result"].attractions
    assert any("LLM action search_attractions" in observation for observation in result["tool_observations"])
    assert trip_plan.session_id == "session-graph-001"


def test_travel_planner_graph_writes_hotel_search_result_before_planning() -> None:
    class SearchClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def search_attractions(self, keywords: str, city: str | None = None) -> list[Attraction]:
            self.calls.append(f"attraction:{city}:{keywords}")
            return [
                Attraction(
                    name=f"Museum {index}",
                    city=city,
                    address=f"Museum Road {index}",
                    poi_id=f"POI-{index}",
                    location=Location(longitude=116.3 + index * 0.001, latitude=39.9),
                    rating=4.5,
                )
                for index in range(6)
            ]

        async def search_hotels(self, keywords: str, city: str | None = None) -> list[Hotel]:
            self.calls.append(f"hotel:{city}:{keywords}")
            return [
                Hotel(
                    name=f"Hotel {index}",
                    city=city,
                    poi_id=f"HOTEL-{index}",
                    location=Location(longitude=116.4 + index * 0.001, latitude=39.91),
                    rating=4.4,
                    estimated_cost=450,
                )
                for index in range(4)
            ]

        async def get_weather(self, city: str) -> list[WeatherInfo]:
            return []

    async def run_graph() -> tuple[TravelPlanState, SearchClient]:
        client = SearchClient()
        graph = build_travel_planner_graph(amap_client=client, llm_service=FakeAttractionLLM())
        request = make_request()
        result = await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )
        return result, client

    result, client = asyncio.run(run_graph())

    trip_plan = TripPlan.model_validate(result["trip_plan"])
    assert client.calls == ["attraction:Beijing:museum", "hotel:Beijing:budget hotel"]
    assert result["hotel_search_result"].selected_hotel is not None
    assert len(result["hotel_search_result"].candidate_hotels) == 4
    assert result["hotels"] == result["hotel_search_result"].candidate_hotels
    assert any("LLM action search_hotels" in observation for observation in result["tool_observations"])
    assert trip_plan.session_id == "session-graph-001"


def test_travel_planner_graph_keeps_planning_when_attraction_search_fails() -> None:
    class FailingSearchClient:
        async def search_attractions(self, keywords: str, city: str | None = None) -> list[Attraction]:
            raise RuntimeError("attraction search unavailable")

        async def get_weather(self, city: str) -> list[WeatherInfo]:
            return [
                WeatherInfo(
                    city=city,
                    date=date(2026, 6, 10),
                    day_weather="sunny",
                    night_weather="cloudy",
                    day_temp=28,
                    night_temp=18,
                )
            ]

    async def run_graph() -> TravelPlanState:
        graph = build_travel_planner_graph(amap_client=FailingSearchClient(), llm_service=FakeAttractionLLM())
        request = make_request()
        return await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )

    result = asyncio.run(run_graph())

    trip_plan = TripPlan.model_validate(result["trip_plan"])
    assert result["attractions"] == []
    assert len(result["weather_info"]) == 1
    assert trip_plan.weather_info == result["weather_info"]
    assert any("Attraction search tool failure" in observation for observation in result["tool_observations"])


def test_travel_planner_graph_repairs_business_validation_errors_without_requiring_meals() -> None:
    async def run_graph() -> tuple[TravelPlanState, RepairingPlannerLLM]:
        llm = RepairingPlannerLLM()
        graph = build_travel_planner_graph(llm_service=llm)
        request = make_request()
        result = await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )
        return result, llm

    result, llm = asyncio.run(run_graph())
    trip_plan = TripPlan.model_validate(result["trip_plan"])

    assert llm.planner_calls == 2
    assert result["validation_errors"] == []
    assert result["retry_count"] == 1
    assert trip_plan.overall_suggestions == "Fixed by repair."
    assert trip_plan.days[0].meals == []
    assert any("Validation failed" in observation for observation in result["tool_observations"])


def test_travel_planner_graph_falls_back_after_repair_limit() -> None:
    async def run_graph() -> tuple[TravelPlanState, AlwaysInvalidPlannerLLM]:
        llm = AlwaysInvalidPlannerLLM()
        graph = build_travel_planner_graph(llm_service=llm)
        request = make_request()
        result = await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )
        return result, llm

    result, llm = asyncio.run(run_graph())
    trip_plan = TripPlan.model_validate(result["trip_plan"])

    assert llm.planner_calls == 3
    assert result["validation_errors"]
    assert result["retry_count"] == 3
    assert trip_plan.overall_suggestions != "Invalid business plan."
    assert any("FallbackNode returned deterministic plan" in observation for observation in result["tool_observations"])


def test_travel_planner_graph_restores_working_memory_for_same_thread_id() -> None:
    async def run_graph() -> tuple[TravelPlanState, TravelPlanState]:
        graph = build_travel_planner_graph(checkpointer=InMemorySaver())
        first_request = make_request().model_copy(update={"extra_requirements": "First session detail"})
        second_request = make_request().model_copy(update={"extra_requirements": "Second session detail"})
        config = {"configurable": {"thread_id": first_request.session_id}}

        first_result = await graph.ainvoke({"request": first_request}, config=config)
        second_result = await graph.ainvoke({"request": second_request}, config=config)
        return first_result, second_result

    first_result, second_result = asyncio.run(run_graph())

    first_messages = [message["content"] for message in first_result["working_messages"]]
    second_messages = [message["content"] for message in second_result["working_messages"]]
    assert any("First session detail" in message for message in first_messages)
    assert any("First session detail" in message for message in second_messages)
    assert any("Second session detail" in message for message in second_messages)
    assert len(second_result["working_messages"]) > len(first_result["working_messages"])


def test_travel_planner_graph_extracts_memory_candidates_after_valid_trip_plan() -> None:
    async def run_graph() -> TravelPlanState:
        graph = build_travel_planner_graph()
        request = make_request().model_copy(update={"extra_requirements": "我喜欢轻松节奏，不要太赶。"})
        return await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )

    result = asyncio.run(run_graph())

    assert any(
        candidate.target == "semantic" and "轻松节奏" in candidate.text
        for candidate in result["memory_candidates"]
    )
    assert any(candidate.target == "episodic" for candidate in result["memory_candidates"])


def test_travel_planner_graph_loads_long_term_memory_before_planning() -> None:
    class FakeLongTermMemoryStore:
        def __init__(self) -> None:
            self.semantic_queries: list[str] = []
            self.episodic_queries: list[str] = []

        async def search_semantic(self, user_id: str, query: str, limit: int | None = None) -> list[dict]:
            self.semantic_queries.append(f"{user_id}:{query}:{limit}")
            return [{"text": "User prefers relaxed travel.", "target": "semantic"}]

        async def search_episodic(self, user_id: str, query: str, limit: int | None = None) -> list[dict]:
            self.episodic_queries.append(f"{user_id}:{query}:{limit}")
            return [{"text": "User previously selected a city-center hotel.", "target": "episodic"}]

        async def save_candidates(self, user_id: str, candidates: list) -> int:
            return 0

    async def run_graph() -> tuple[TravelPlanState, FakeLongTermMemoryStore]:
        store = FakeLongTermMemoryStore()
        graph = build_travel_planner_graph(long_term_store=store)
        request = make_request()
        result = await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )
        return result, store

    result, store = asyncio.run(run_graph())

    assert store.semantic_queries
    assert "Beijing" in store.semantic_queries[0]
    assert result["semantic_memories"] == [{"text": "User prefers relaxed travel.", "target": "semantic"}]
    assert result["episodic_memories"] == [
        {"text": "User previously selected a city-center hotel.", "target": "episodic"}
    ]
    assert "Known User Preferences" in result["planner_context"]
    assert "User prefers relaxed travel." in result["planner_context"]


def test_travel_planner_graph_saves_long_term_memory_after_valid_trip_plan() -> None:
    class FakeLongTermMemoryStore:
        def __init__(self) -> None:
            self.saved: list[tuple[str, list]] = []

        async def search_semantic(self, user_id: str, query: str, limit: int | None = None) -> list[dict]:
            return []

        async def search_episodic(self, user_id: str, query: str, limit: int | None = None) -> list[dict]:
            return []

        async def save_candidates(self, user_id: str, candidates: list) -> int:
            self.saved.append((user_id, list(candidates)))
            return len([candidate for candidate in candidates if candidate.target != "discard"])

    async def run_graph() -> tuple[TravelPlanState, FakeLongTermMemoryStore]:
        store = FakeLongTermMemoryStore()
        graph = build_travel_planner_graph(long_term_store=store)
        request = make_request().model_copy(update={"extra_requirements": "Prefer relaxed cultural attractions."})
        result = await graph.ainvoke(
            {"request": request},
            config={"configurable": {"thread_id": request.session_id}},
        )
        return result, store

    result, store = asyncio.run(run_graph())

    assert store.saved
    assert store.saved[0][0] == "user-001"
    assert any(candidate.target == "semantic" for candidate in store.saved[0][1])
    assert any(candidate.target == "episodic" for candidate in store.saved[0][1])
    assert any("Long-term memory saved" in observation for observation in result["tool_observations"])


def test_weather_node_extracts_memory_candidates_when_tool_observations_overflow() -> None:
    class WeatherClient:
        async def get_weather(self, city: str) -> list[WeatherInfo]:
            return []

    async def run_node() -> TravelPlanState:
        node = make_weather_query_node(WeatherClient())
        state = {
            "normalized_request": make_request().model_copy(update={"session_id": "session-graph-001"}),
            "weather_info": [],
            "memory_candidates": [],
            "tool_observations": [
                "用户选择了王府井附近酒店。",
                *[f"observation {index}" for index in range(50)],
            ],
        }
        return await node(state)

    result = asyncio.run(run_node())

    assert len(result["tool_observations"]) == 50
    assert any(candidate.target == "episodic" and "王府井" in candidate.text for candidate in result["memory_candidates"])
