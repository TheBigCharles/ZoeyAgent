"""TravelPlannerGraph nodes for the controlled planning path."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.config import exception_details
from app.schemas.domain import Attraction, DayPlan, Hotel, Meal
from app.schemas.graph import NormalizedTripRequest, TravelPlanState
from app.schemas.trip import TripPlan
from app.services.amap_service import build_map_points
from app.services.llm_service import validate_structured_output


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


def make_planner_node(llm_service: Any | None = None):
    async def node(state: TravelPlanState) -> dict[str, Any]:
        if llm_service is not None:
            try:
                return {"trip_plan": await _generate_llm_trip_plan(state, llm_service)}
            except Exception as exc:
                observations = list(state.get("tool_observations", []))
                observations.append(f"Planner LLM failed; used deterministic fallback. {exception_details(exc)}")
                fallback = _build_deterministic_trip_plan(state)
                return {
                    "trip_plan": fallback,
                    "tool_observations": observations,
                }

        return {"trip_plan": _build_deterministic_trip_plan(state)}

    return node


async def planner_node(state: TravelPlanState) -> dict[str, Any]:
    return await make_planner_node()(state)


async def _generate_llm_trip_plan(state: TravelPlanState, llm_service: Any) -> TripPlan:
    response = await llm_service.complete(_planner_messages(state), temperature=0)
    return validate_structured_output(response, TripPlan)


def _planner_messages(state: TravelPlanState) -> list[dict[str, str]]:
    normalized = state["normalized_request"]
    return [
        {
            "role": "system",
            "content": (
                "你是主旅行规划 PlannerNode。只返回合法 JSON，不要返回 markdown。"
                "输出必须匹配 TripPlan schema，并包含 resolved session_id。"
                "必须为每一天生成 exactly one breakfast, one lunch, one dinner。"
                "可以使用 route_distance_km、route_duration_minutes、transit_method 这类路线摘要，"
                "不要输出完整 turn-by-turn 路线步骤，不要求 image_url。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"TripPlan schema\n"
                f"- session_id: string\n"
                f"- cities: list[string]\n"
                f"- start_date/end_date: date\n"
                f"- days: list[DayPlan]\n"
                f"- weather_info: list[WeatherInfo]\n"
                f"- overall_suggestions: string\n\n"
                f"resolved_session_id={normalized.session_id}\n"
                f"cities={normalized.cities}\n"
                f"date_range={normalized.start_date} to {normalized.end_date}\n"
                f"transport_preference={normalized.transport_preference}\n"
                f"accommodation_preferences={normalized.accommodation_preferences}\n"
                f"attraction_preferences={normalized.attraction_preferences}\n"
                f"budget={normalized.budget}\n"
                f"extra_requirements={normalized.extra_requirements}\n\n"
                f"planner_context=\n{state.get('planner_context', '')}\n\n"
                f"attraction_candidates={_dump_models(state.get('attractions', []))}\n"
                f"hotel_candidates={_dump_models(state.get('hotels', []))}\n"
                f"weather_info={_dump_models(state.get('weather_info', []))}\n"
            ),
        },
    ]


def _dump_models(values: list[Any]) -> list[Any]:
    dumped = []
    for value in values:
        if hasattr(value, "model_dump"):
            dumped.append(value.model_dump(mode="json"))
        else:
            dumped.append(value)
    return dumped


def _build_deterministic_trip_plan(state: TravelPlanState) -> TripPlan:
    normalized = state["normalized_request"]
    days = []
    attractions = list(state.get("attractions", []))
    hotel = _selected_hotel(state)

    for day_index in range(normalized.days_count):
        current_date = normalized.start_date + timedelta(days=day_index)
        city = normalized.cities[min(day_index, len(normalized.cities) - 1)]
        day_attractions = _attractions_for_day(attractions, day_index, normalized.days_count)
        meals = _default_meals(city)
        map_points = build_map_points(
            day_index=day_index,
            attractions=day_attractions,
            hotel=hotel,
            meals=meals,
        )
        days.append(
            DayPlan(
                date=current_date,
                day_index=day_index,
                city=city,
                description=_day_description(day_index, city, day_attractions, hotel),
                transportation=normalized.transport_preference,
                accommodation=", ".join(normalized.accommodation_preferences),
                hotel=hotel,
                attractions=day_attractions,
                meals=meals,
                map_points=map_points,
                total_price=_estimate_day_total(day_attractions, hotel, meals),
                route_distance_km=hotel.distance_to_main_area_km if hotel else None,
                route_duration_minutes=hotel.estimated_travel_time_minutes if hotel else None,
                transit_method=hotel.transit_method if hotel else None,
            )
        )

    return TripPlan(
        session_id=normalized.session_id,
        cities=normalized.cities,
        start_date=normalized.start_date,
        end_date=normalized.end_date,
        days=days,
        weather_info=state.get("weather_info", []),
        overall_suggestions=_overall_suggestions(normalized, attractions, hotel),
    )


def _selected_hotel(state: TravelPlanState) -> Hotel | None:
    hotel_result = state.get("hotel_search_result")
    if hotel_result is not None and hotel_result.selected_hotel is not None:
        return hotel_result.selected_hotel
    hotels = list(state.get("hotels", []))
    return hotels[0] if hotels else None


def _attractions_for_day(attractions: list[Attraction], day_index: int, days_count: int) -> list[Attraction]:
    if not attractions:
        return []
    chunk_size = max(1, (len(attractions) + max(days_count, 1) - 1) // max(days_count, 1))
    start = day_index * chunk_size
    end = start + chunk_size
    return [
        attraction.model_copy(update={"order_index": order_index})
        for order_index, attraction in enumerate(attractions[start:end])
    ]


def _default_meals(city: str) -> list[Meal]:
    return [
        Meal(type="breakfast", name=f"{city} breakfast suggestion", city=city, estimated_cost=20),
        Meal(type="lunch", name=f"{city} lunch suggestion", city=city, estimated_cost=20),
        Meal(type="dinner", name=f"{city} dinner suggestion", city=city, estimated_cost=20),
    ]


def _estimate_day_total(attractions: list[Attraction], hotel: Hotel | None, meals: list[Meal]) -> int:
    attraction_total = sum(attraction.ticket_price for attraction in attractions)
    meal_total = sum(meal.estimated_cost for meal in meals)
    hotel_total = hotel.estimated_cost if hotel is not None else 0
    return attraction_total + meal_total + hotel_total


def _day_description(day_index: int, city: str, attractions: list[Attraction], hotel: Hotel | None) -> str:
    attraction_names = "、".join(attraction.name for attraction in attractions) or "轻松探索城市"
    hotel_part = f"，入住 {hotel.name}" if hotel is not None else ""
    return f"第 {day_index + 1} 天在 {city} 安排 {attraction_names}{hotel_part}。"


def _overall_suggestions(normalized: NormalizedTripRequest, attractions: list[Attraction], hotel: Hotel | None) -> str:
    hotel_text = f"推荐住宿为 {hotel.name}。" if hotel is not None else "当前没有可用酒店候选。"
    return (
        f"本行程按 {normalized.transport_preference} 出行偏好安排，"
        f"共使用 {len(attractions)} 个景点候选。{hotel_text}"
    )


async def validate_trip_plan(state: TravelPlanState) -> dict[str, Any]:
    trip_plan = TripPlan.model_validate(state["trip_plan"])
    return {
        "trip_plan": trip_plan,
        "validation_errors": [],
    }
