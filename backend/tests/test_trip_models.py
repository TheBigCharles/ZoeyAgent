from datetime import date

import pytest
from pydantic import ValidationError

from app.models.domain import (
    Attraction,
    DayPlan,
    Hotel,
    Location,
    Meal,
    MapPoint,
    WeatherInfo,
)
from app.models.trip import (
    AccommodationPreference,
    AttractionPreference,
    TransportPreference,
    TripPlan,
    TripPlanRequest,
    TripPreferencesInput,
)


def make_preferences() -> TripPreferencesInput:
    return TripPreferencesInput(
        transport_preference=0,
        accommodation_preference=[0],
        attraction_preference=[0, 1],
    )


def test_trip_plan_request_validates_and_normalizes_form_input() -> None:
    request = TripPlanRequest(
        user_id="user-001",
        session_id="session-001",
        cities=[" 北京 ", "", "上海"],
        start_date="2026-06-10",
        end_date="2026-06-12",
        preferences=make_preferences(),
        budget=3000,
        extra_requirements="不要安排太赶",
    )

    assert request.cities == ["北京", "上海"]
    assert request.start_date == date(2026, 6, 10)
    assert request.end_date == date(2026, 6, 12)
    assert request.preferences.transport_preference is TransportPreference.PUBLIC_TRANSPORT
    assert request.preferences.accommodation_preference == [AccommodationPreference.BUDGET_HOTEL]
    assert request.preferences.attraction_preference == [
        AttractionPreference.HISTORY_CULTURE,
        AttractionPreference.NATURE,
    ]
    assert request.preferences.transport_preference.value_en == "public_transport"
    assert request.preferences.accommodation_preference[0].value_en == "budget_hotel"
    assert request.preferences.attraction_preference[1].value_en == "nature"


def test_trip_plan_request_allows_missing_or_blank_session_id_for_first_request() -> None:
    request = TripPlanRequest(
        user_id="user-001",
        cities=["北京"],
        start_date="2026-06-10",
        end_date="2026-06-12",
        preferences=make_preferences(),
    )

    assert request.session_id is None

    blank_request = TripPlanRequest(
        user_id="user-001",
        session_id="   ",
        cities=["北京"],
        start_date="2026-06-10",
        end_date="2026-06-12",
        preferences=make_preferences(),
    )

    assert blank_request.session_id is None


@pytest.mark.parametrize(
    "payload",
    [
        {"cities": ["   "]},
        {"start_date": "2026-06-12", "end_date": "2026-06-10"},
        {"budget": -1},
        {"preferences": {"transport_preference": 9, "accommodation_preference": [], "attraction_preference": []}},
    ],
)
def test_trip_plan_request_rejects_invalid_input(payload: dict) -> None:
    base = {
        "user_id": "user-001",
        "session_id": "session-001",
        "cities": ["北京"],
        "start_date": "2026-06-10",
        "end_date": "2026-06-12",
        "preferences": {
            "transport_preference": 0,
            "accommodation_preference": [0],
            "attraction_preference": [0, 1],
        },
        "budget": 3000,
    }
    base.update(payload)

    with pytest.raises(ValidationError):
        TripPlanRequest(**base)


def test_weather_info_parses_temperature_strings() -> None:
    weather = WeatherInfo(
        city="北京",
        date="2026-06-10",
        day_weather="晴",
        night_weather="多云",
        day_temp="28℃",
        night_temp="18°C",
    )

    assert weather.day_temp == 28
    assert weather.night_temp == 18


def test_day_plan_requires_exactly_one_meal_of_each_type() -> None:
    hotel = Hotel(name="测试酒店", city="北京", estimated_cost=500)
    attractions = [
        Attraction(
            name="故宫",
            city="北京",
            location=Location(longitude=116.397128, latitude=39.916527),
            order_index=0,
        )
    ]
    meals = [
        Meal(type="breakfast", name="早餐", city="北京"),
        Meal(type="lunch", name="午餐", city="北京"),
        Meal(type="dinner", name="晚餐", city="北京"),
    ]
    map_points = [
        MapPoint(
            name="故宫",
            city="北京",
            location=Location(longitude=116.397128, latitude=39.916527),
            day_index=0,
            order_index=0,
        )
    ]

    day = DayPlan(
        date="2026-06-10",
        day_index=0,
        city="北京",
        description="第一天",
        transportation="public_transport",
        accommodation="budget_hotel",
        hotel=hotel,
        attractions=attractions,
        meals=meals,
        map_points=map_points,
        total_price=800,
    )

    assert day.meals == meals

    with pytest.raises(ValidationError):
        DayPlan(
            date="2026-06-10",
            day_index=0,
            city="北京",
            description="第一天",
            transportation="public_transport",
            accommodation="budget_hotel",
            meals=meals[:2],
            total_price=800,
        )


def test_trip_plan_days_must_match_date_range() -> None:
    day = DayPlan(
        date="2026-06-10",
        day_index=0,
        city="北京",
        description="第一天",
        transportation="public_transport",
        accommodation="budget_hotel",
        meals=[
            Meal(type="breakfast", name="早餐"),
            Meal(type="lunch", name="午餐"),
            Meal(type="dinner", name="晚餐"),
        ],
        total_price=100,
    )

    with pytest.raises(ValidationError):
        TripPlan(
            session_id="session-001",
            cities=["北京"],
            start_date="2026-06-10",
            end_date="2026-06-12",
            days=[day],
            overall_suggestions="轻松游玩",
        )


def test_trip_plan_requires_resolved_session_id_in_response() -> None:
    day = DayPlan(
        date="2026-06-10",
        day_index=0,
        city="北京",
        description="第一天",
        transportation="public_transport",
        accommodation="budget_hotel",
        meals=[
            Meal(type="breakfast", name="早餐"),
            Meal(type="lunch", name="午餐"),
            Meal(type="dinner", name="晚餐"),
        ],
        total_price=100,
    )

    plan = TripPlan(
        session_id="session-001",
        cities=["北京"],
        start_date="2026-06-10",
        end_date="2026-06-10",
        days=[day],
        overall_suggestions="轻松游玩",
    )

    assert plan.session_id == "session-001"

    with pytest.raises(ValidationError):
        TripPlan(
            cities=["北京"],
            start_date="2026-06-10",
            end_date="2026-06-10",
            days=[day],
            overall_suggestions="轻松游玩",
        )

    with pytest.raises(ValidationError):
        TripPlan(
            session_id="   ",
            cities=["北京"],
            start_date="2026-06-10",
            end_date="2026-06-10",
            days=[day],
            overall_suggestions="轻松游玩",
        )
