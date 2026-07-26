import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.trip_planner_agent import build_travel_planner_graph
from app.api.main import create_app
from app.config import AppDependencies
from app.schemas.trip import TripPlan


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "http_requests"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


async def deterministic_dependencies() -> AppDependencies:
    return AppDependencies(graph=build_travel_planner_graph())


def test_e2e_health_endpoint() -> None:
    with TestClient(create_app(dependency_factory=deterministic_dependencies)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_e2e_trip_plan_contract_with_json_fixtures() -> None:
    fixture_names = [
        "trip-request-beijing-public.json",
        "trip-request-beijing-driving.json",
        "trip-request-multi-city-budget-null.json",
    ]

    with TestClient(create_app(dependency_factory=deterministic_dependencies)) as client:
        for fixture_name in fixture_names:
            payload = load_fixture(fixture_name)
            response = client.post("/api/trip/plan", json=payload)

            assert response.status_code == 200, response.text
            trip_plan = TripPlan.model_validate(response.json())
            assert trip_plan.session_id
            assert trip_plan.cities == payload["cities"]
            expected_days = (
                trip_plan.end_date
                - trip_plan.start_date
            ).days + 1
            assert len(trip_plan.days) == expected_days
            assert [day.day_index for day in trip_plan.days] == list(range(expected_days))
            assert all(day.total_price >= 0 for day in trip_plan.days)


def test_e2e_trip_plan_continues_when_weather_tool_fails() -> None:
    class FailingWeatherClient:
        async def get_weather(self, city: str):
            raise RuntimeError(f"weather unavailable for {city}")

    async def fake_dependencies() -> AppDependencies:
        return AppDependencies(graph=build_travel_planner_graph(amap_client=FailingWeatherClient()))

    with TestClient(create_app(dependency_factory=fake_dependencies)) as client:
        response = client.post("/api/trip/plan", json=load_fixture("trip-request-tool-failure.json"))

    assert response.status_code == 200
    trip_plan = TripPlan.model_validate(response.json())
    assert trip_plan.weather_info == []
    assert trip_plan.days


def test_e2e_planner_validation_retry_repairs_bad_first_output() -> None:
    class RepairingPlannerLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages: list[dict], **_: object) -> dict:
            self.calls += 1
            payload = invalid_trip_plan_payload() if self.calls == 1 else valid_trip_plan_payload()
            return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    llm = RepairingPlannerLLM()

    async def fake_dependencies() -> AppDependencies:
        return AppDependencies(graph=build_travel_planner_graph(llm_service=llm))

    with TestClient(create_app(dependency_factory=fake_dependencies)) as client:
        response = client.post("/api/trip/plan", json=load_fixture("trip-request-validation-retry.json"))

    assert response.status_code == 200
    assert llm.calls == 2
    trip_plan = TripPlan.model_validate(response.json())
    assert trip_plan.days[0].description == "Planner repaired this plan."


def test_e2e_memory_search_contract_with_json_fixture() -> None:
    class FakeMemoryStore:
        async def search_semantic(self, user_id: str, query: str | None = None, limit: int | None = None):
            return [{"key": "semantic-001", "text": f"{user_id}: {query}", "score": 0.9}]

        async def search_episodic(self, user_id: str, query: str | None = None, limit: int | None = None):
            return [{"key": "episodic-001", "text": f"{user_id}: prior decision", "score": 0.8}]

    async def fake_dependencies() -> AppDependencies:
        return AppDependencies(graph=object(), store=FakeMemoryStore())

    fixture = load_fixture("memory-query-semantic.json")
    with TestClient(create_app(dependency_factory=fake_dependencies)) as client:
        response = client.get("/api/memory/semantic", params=fixture)

    assert response.status_code == 200
    payload = response.json()
    assert payload["memory_type"] == "semantic"
    assert payload["user_id"] == fixture["user_id"]
    assert payload["query"] == fixture["query"]
    assert payload["count"] == 1


def test_e2e_recalculate_reserved_contract_with_json_fixture() -> None:
    with TestClient(create_app(dependency_factory=deterministic_dependencies)) as client:
        response = client.post("/api/trip/recalculate", json=load_fixture("trip-recalculate-request.json"))

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "TRIP_RECALCULATION_NOT_IMPLEMENTED"


def invalid_trip_plan_payload() -> dict:
    return {
        "session_id": "validation-retry-session",
        "cities": ["北京"],
        "start_date": "2026-06-20",
        "end_date": "2026-06-20",
        "days": [
            {
                "date": "2026-06-21",
                "day_index": 0,
                "city": "北京",
                "description": "Wrong date for retry.",
                "transportation": "public_transport",
                "accommodation": "budget_hotel",
                "meals": [],
                "total_price": 0,
            }
        ],
        "weather_info": [],
        "overall_suggestions": "Invalid first planner output.",
    }


def valid_trip_plan_payload() -> dict:
    return {
        "session_id": "validation-retry-session",
        "cities": ["北京"],
        "start_date": "2026-06-20",
        "end_date": "2026-06-20",
        "days": [
            {
                "date": "2026-06-20",
                "day_index": 0,
                "city": "北京",
                "description": "Planner repaired this plan.",
                "transportation": "public_transport",
                "accommodation": "budget_hotel",
                "meals": [],
                "total_price": 0,
            }
        ],
        "weather_info": [],
        "overall_suggestions": "Valid repaired planner output.",
    }
