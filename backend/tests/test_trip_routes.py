from uuid import UUID

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.trip import TripPlan


def minimal_trip_request() -> dict:
    return {
        "user_id": "user-001",
        "cities": ["Beijing"],
        "start_date": "2026-06-10",
        "end_date": "2026-06-12",
        "preferences": {
            "transport_preference": 0,
            "accommodation_preference": [0],
            "attraction_preference": [0, 1],
        },
        "budget": 3000,
        "extra_requirements": "Keep the pace relaxed",
    }


def test_plan_endpoint_generates_session_id_for_first_request() -> None:
    client = TestClient(create_app())

    response = client.post("/api/trip/plan", json=minimal_trip_request())

    assert response.status_code == 200
    trip_plan = TripPlan.model_validate(response.json())
    UUID(trip_plan.session_id)
    assert trip_plan.cities == ["Beijing"]
    assert len(trip_plan.days) == 3
    assert [meal.type for meal in trip_plan.days[0].meals] == ["breakfast", "lunch", "dinner"]


def test_plan_endpoint_reuses_existing_session_id() -> None:
    client = TestClient(create_app())
    payload = minimal_trip_request()
    payload["session_id"] = "existing-session-001"

    response = client.post("/api/trip/plan", json=payload)

    assert response.status_code == 200
    trip_plan = TripPlan.model_validate(response.json())
    assert trip_plan.session_id == "existing-session-001"
