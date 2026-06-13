"""Minimal TravelPlannerGraph nodes for the controlled planning path."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.schemas.domain import DayPlan, Meal
from app.schemas.graph import NormalizedTripRequest, TravelPlanState
from app.schemas.trip import TripPlan


async def initialize_working_state(state: TravelPlanState) -> dict[str, Any]:
    request = state["request"]
    return {
        "working_messages": state.get(
            "working_messages",
            [
                {
                    "role": "user",
                    "content": (
                        f"Plan a trip to {', '.join(request.cities)} "
                        f"from {request.start_date} to {request.end_date}."
                    ),
                }
            ],
        ),
        "trip_draft": state.get("trip_draft", {}),
        "tool_observations": state.get("tool_observations", []),
        "memory_candidates": state.get("memory_candidates", []),
        "semantic_memories": state.get("semantic_memories", []),
        "episodic_memories": state.get("episodic_memories", []),
        "context_packets": state.get("context_packets", []),
        "planner_context": state.get("planner_context", ""),
        "attractions": state.get("attractions", []),
        "weather_info": state.get("weather_info", []),
        "hotels": state.get("hotels", []),
        "trip_plan": state.get("trip_plan"),
        "validation_errors": state.get("validation_errors", []),
        "retry_count": state.get("retry_count", 0),
    }


async def normalize_request(state: TravelPlanState) -> dict[str, NormalizedTripRequest]:
    request = state["request"]
    days_count = (request.end_date - request.start_date).days + 1
    return {
        "normalized_request": NormalizedTripRequest(
            user_id=request.user_id,
            cities=request.cities,
            start_date=request.start_date,
            end_date=request.end_date,
            days_count=days_count,
            transport_preference=request.preferences.transport_preference.value_en,
            accommodation_preferences=[
                preference.value_en for preference in request.preferences.accommodation_preference
            ],
            attraction_preferences=[
                preference.value_en for preference in request.preferences.attraction_preference
            ],
            budget=request.budget,
            extra_requirements=request.extra_requirements,
            session_id=request.session_id or "",
        )
    }


def make_weather_query_node(amap_client: Any | None = None):
    async def weather_query_node(state: TravelPlanState) -> dict[str, Any]:
        weather_info = list(state.get("weather_info", []))
        observations = list(state.get("tool_observations", []))

        if amap_client is None:
            return {
                "weather_info": weather_info,
                "tool_observations": observations,
            }

        normalized = state["normalized_request"]
        for city in dict.fromkeys(normalized.cities):
            try:
                city_weather = await amap_client.get_weather(city)
            except Exception as exc:
                observations.append(f"Amap weather query for {city} failed: {type(exc).__name__}.")
                continue

            weather_info.extend(city_weather)
            observations.append(f"Amap weather query for {city} returned {len(city_weather)} records.")

        return {
            "weather_info": weather_info,
            "tool_observations": observations,
        }

    return weather_query_node


async def planner_node(state: TravelPlanState) -> dict[str, TripPlan]:
    normalized = state["normalized_request"]
    days = []

    for day_index in range(normalized.days_count):
        current_date = normalized.start_date + timedelta(days=day_index)
        city = normalized.cities[min(day_index, len(normalized.cities) - 1)]
        days.append(
            DayPlan(
                date=current_date,
                day_index=day_index,
                city=city,
                description=f"Mock itinerary for day {day_index + 1} in {city}.",
                transportation=normalized.transport_preference,
                accommodation=", ".join(normalized.accommodation_preferences),
                meals=[
                    Meal(type="breakfast", name="Mock breakfast", city=city),
                    Meal(type="lunch", name="Mock lunch", city=city),
                    Meal(type="dinner", name="Mock dinner", city=city),
                ],
                total_price=0,
            )
        )

    return {
        "trip_plan": TripPlan(
            session_id=normalized.session_id,
            cities=normalized.cities,
            start_date=normalized.start_date,
            end_date=normalized.end_date,
            days=days,
            weather_info=state.get("weather_info", []),
            overall_suggestions="Mock trip plan generated by TravelPlannerGraph.",
        )
    }


async def validate_trip_plan(state: TravelPlanState) -> dict[str, Any]:
    trip_plan = TripPlan.model_validate(state["trip_plan"])
    return {
        "trip_plan": trip_plan,
        "validation_errors": [],
    }
