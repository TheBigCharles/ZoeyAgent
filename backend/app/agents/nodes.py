"""TravelPlannerGraph nodes for the controlled planning path."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.config import exception_details
from app.schemas.domain import Attraction, DayPlan, Hotel, Meal
from app.schemas.graph import NormalizedTripRequest, TravelPlanState
from app.schemas.memory import MemoryCandidate
from app.schemas.trip import TripPlan
from app.services.amap_service import build_map_points
from app.services.llm_service import validate_structured_output
from app.agents.working_memory import (
    maintain_tool_observations,
    maintain_working_messages,
    merge_memory_candidates,
)
from app.memory.extraction import MemoryExtractionService


MAX_REPAIR_ATTEMPTS = 2
DEFAULT_MAX_ATTRACTIONS_PER_DAY = 4
RELAXED_MAX_ATTRACTIONS_PER_DAY = 3
HOTEL_COST_ESTIMATES = {
    "budget_hotel": 300,
    "mid_level_hotel": 600,
    "five_star_hotel": 1200,
}
RELAXED_REQUIREMENT_HINTS = ("relaxed", "轻松", "不赶", "不要太赶", "慢节奏", "悠闲")


async def initialize_working_state(state: TravelPlanState) -> dict[str, Any]:
    request = state["request"]
    working_message = {
        "role": "user",
        "content": (
            f"Plan a trip to {', '.join(request.cities)} "
            f"from {request.start_date} to {request.end_date}. "
            f"Extra requirements: {request.extra_requirements or '(none)'}"
        ),
    }
    memory_candidates = list(state.get("memory_candidates", []))
    working_result = maintain_working_messages(
        state.get("working_messages"),
        working_message,
        extraction_service=MemoryExtractionService(),
        existing_candidates=memory_candidates,
    )
    memory_candidates = merge_memory_candidates(memory_candidates, working_result.extracted_candidates)
    tool_result = maintain_tool_observations(
        state.get("tool_observations"),
        None,
        extraction_service=MemoryExtractionService(),
        existing_candidates=memory_candidates,
    )
    memory_candidates = merge_memory_candidates(memory_candidates, tool_result.extracted_candidates)
    return {
        "working_messages": working_result.retained_messages,
        "trip_draft": {},
        "tool_observations": tool_result.retained_messages,
        "memory_candidates": memory_candidates,
        "semantic_memories": state.get("semantic_memories", []),
        "episodic_memories": state.get("episodic_memories", []),
        "context_packets": [],
        "planner_context": "",
        "attractions": [],
        "weather_info": [],
        "hotels": [],
        "trip_plan": None,
        "validation_errors": [],
        "retry_count": 0,
    }


def make_load_memory_node(long_term_store: Any | None = None):
    async def load_memory_node(state: TravelPlanState) -> dict[str, Any]:
        semantic_memories = list(state.get("semantic_memories", []))
        episodic_memories = list(state.get("episodic_memories", []))
        observations = list(state.get("tool_observations", []))
        memory_candidates = list(state.get("memory_candidates", []))

        if long_term_store is None:
            return {
                "semantic_memories": semantic_memories,
                "episodic_memories": episodic_memories,
                "tool_observations": observations,
                "memory_candidates": memory_candidates,
            }

        request = state["request"]
        query = _memory_recall_query(request)
        try:
            semantic_memories = await long_term_store.search_semantic(request.user_id, query, limit=None)
            episodic_memories = await long_term_store.search_episodic(request.user_id, query, limit=None)
            observations, memory_candidates = _maintain_tool_observation(
                observations,
                (
                    "Long-term memory loaded "
                    f"{len(semantic_memories)} semantic and {len(episodic_memories)} episodic records."
                ),
                memory_candidates,
            )
        except Exception as exc:
            observations, memory_candidates = _maintain_tool_observation(
                observations,
                f"Long-term memory load failed: {type(exc).__name__}.",
                memory_candidates,
            )

        return {
            "semantic_memories": semantic_memories,
            "episodic_memories": episodic_memories,
            "tool_observations": observations,
            "memory_candidates": memory_candidates,
        }

    return load_memory_node


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
        memory_candidates = list(state.get("memory_candidates", []))

        if amap_client is None:
            return {
                "weather_info": weather_info,
                "tool_observations": observations,
                "memory_candidates": memory_candidates,
            }

        normalized = state["normalized_request"]
        for city in dict.fromkeys(normalized.cities):
            try:
                city_weather = await amap_client.get_weather(city)
            except Exception as exc:
                observations, memory_candidates = _maintain_tool_observation(
                    observations,
                    f"Amap weather query for {city} failed: {type(exc).__name__}.",
                    memory_candidates,
                )
                continue

            weather_info.extend(city_weather)
            observations, memory_candidates = _maintain_tool_observation(
                observations,
                f"Amap weather query for {city} returned {len(city_weather)} records.",
                memory_candidates,
            )

        return {
            "weather_info": weather_info,
            "tool_observations": observations,
            "memory_candidates": memory_candidates,
        }

    return weather_query_node


def make_planner_node(llm_service: Any | None = None):
    async def node(state: TravelPlanState) -> dict[str, Any]:
        if llm_service is not None:
            try:
                return {"trip_plan": await _generate_llm_trip_plan(state, llm_service)}
            except Exception as exc:
                observations = list(state.get("tool_observations", []))
                observations, memory_candidates = _maintain_tool_observation(
                    observations,
                    f"Planner LLM failed; used deterministic fallback. {exception_details(exc)}",
                    state.get("memory_candidates", []),
                )
                fallback = _build_deterministic_trip_plan(state)
                return {
                    "trip_plan": fallback,
                    "tool_observations": observations,
                    "memory_candidates": memory_candidates,
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
                "餐食规划暂时 deferred；meals 可以为空或只包含已有候选，不要为了凑三餐编造餐厅。"
                "轻松行程每天最多安排 3 个景点，普通行程每天最多安排 4 个景点；不要把全部候选塞进单日。"
                "如果酒店候选缺少实时价格，只能使用 estimated_cost 作为估算值，不要声称是真实房价。"
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
                f"previous_validation_errors={state.get('validation_errors', [])}\n"
                f"repair_attempt_count={state.get('retry_count', 0)}\n\n"
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
    hotel = _selected_hotel(state, normalized)

    for day_index in range(normalized.days_count):
        current_date = normalized.start_date + timedelta(days=day_index)
        city = normalized.cities[min(day_index, len(normalized.cities) - 1)]
        day_attractions = _attractions_for_day(attractions, day_index, normalized)
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


def _selected_hotel(state: TravelPlanState, normalized: NormalizedTripRequest) -> Hotel | None:
    hotel_result = state.get("hotel_search_result")
    if hotel_result is not None and hotel_result.selected_hotel is not None:
        return _with_estimated_hotel_cost(hotel_result.selected_hotel, normalized)
    hotels = list(state.get("hotels", []))
    return _with_estimated_hotel_cost(hotels[0], normalized) if hotels else None


def _attractions_for_day(
    attractions: list[Attraction],
    day_index: int,
    normalized: NormalizedTripRequest,
) -> list[Attraction]:
    if not attractions:
        return []
    days_count = max(normalized.days_count, 1)
    chunk_size = min(
        _max_attractions_per_day(normalized),
        max(1, (len(attractions) + days_count - 1) // days_count),
    )
    start = day_index * chunk_size
    end = start + chunk_size
    return [
        attraction.model_copy(update={"order_index": order_index})
        for order_index, attraction in enumerate(attractions[start:end])
    ]


def _max_attractions_per_day(normalized: NormalizedTripRequest) -> int:
    if any(hint in normalized.extra_requirements.lower() for hint in RELAXED_REQUIREMENT_HINTS):
        return RELAXED_MAX_ATTRACTIONS_PER_DAY
    return DEFAULT_MAX_ATTRACTIONS_PER_DAY


def _with_estimated_hotel_cost(hotel: Hotel, normalized: NormalizedTripRequest) -> Hotel:
    if hotel.estimated_cost > 0:
        return hotel
    return hotel.model_copy(update={"estimated_cost": _fallback_hotel_cost(normalized)})


def _fallback_hotel_cost(normalized: NormalizedTripRequest) -> int:
    for preference in normalized.accommodation_preferences:
        estimate = HOTEL_COST_ESTIMATES.get(preference)
        if estimate is not None:
            return estimate
    return HOTEL_COST_ESTIMATES["mid_level_hotel"]


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
    observations = list(state.get("tool_observations", []))
    memory_candidates = list(state.get("memory_candidates", []))
    try:
        trip_plan = TripPlan.model_validate(state["trip_plan"])
    except Exception as exc:
        errors = [f"TripPlan schema validation failed: {type(exc).__name__}."]
        observations, memory_candidates = _maintain_tool_observation(
            observations,
            f"Validation failed: {'; '.join(errors)}",
            memory_candidates,
        )
        return {
            "validation_errors": errors,
            "retry_count": state.get("retry_count", 0) + 1,
            "tool_observations": observations,
            "memory_candidates": memory_candidates,
        }

    errors = _business_validation_errors(trip_plan, state)
    if errors:
        observations, memory_candidates = _maintain_tool_observation(
            observations,
            f"Validation failed: {'; '.join(errors)}",
            memory_candidates,
        )
        return {
            "trip_plan": trip_plan,
            "validation_errors": errors,
            "retry_count": state.get("retry_count", 0) + 1,
            "tool_observations": observations,
            "memory_candidates": memory_candidates,
        }

    return {
        "trip_plan": trip_plan,
        "validation_errors": [],
    }


def route_after_validation(state: TravelPlanState) -> str:
    if not state.get("validation_errors"):
        return "valid"
    if state.get("retry_count", 0) <= MAX_REPAIR_ATTEMPTS:
        return "repair"
    return "fallback"


async def fallback_node(state: TravelPlanState) -> dict[str, Any]:
    observations = list(state.get("tool_observations", []))
    observations, memory_candidates = _maintain_tool_observation(
        observations,
        "FallbackNode returned deterministic plan after repair limit.",
        state.get("memory_candidates", []),
    )
    return {
        "trip_plan": _build_deterministic_trip_plan(state),
        "tool_observations": observations,
        "memory_candidates": memory_candidates,
    }


async def save_memory_node(state: TravelPlanState) -> dict[str, Any]:
    return await make_save_memory_node()(state)


def make_save_memory_node(long_term_store: Any | None = None):
    async def node(state: TravelPlanState) -> dict[str, Any]:
        trip_plan = TripPlan.model_validate(state["trip_plan"])
        existing_candidates = list(state.get("memory_candidates", []))
        extracted = MemoryExtractionService().extract_from_final_plan(
            trip_plan=trip_plan,
            working_messages=state.get("working_messages", []),
            tool_observations=state.get("tool_observations", []),
            existing_candidates=existing_candidates,
        )
        memory_candidates = merge_memory_candidates(existing_candidates, extracted)
        observations = list(state.get("tool_observations", []))

        if long_term_store is not None:
            try:
                saved_count = await long_term_store.save_candidates(state["request"].user_id, memory_candidates)
                observations, memory_candidates = _maintain_tool_observation(
                    observations,
                    f"Long-term memory saved {saved_count} records.",
                    memory_candidates,
                )
            except Exception as exc:
                observations, memory_candidates = _maintain_tool_observation(
                    observations,
                    f"Long-term memory save failed: {type(exc).__name__}.",
                    memory_candidates,
                )

        return {
            "memory_candidates": memory_candidates,
            "tool_observations": observations,
        }

    return node


async def _legacy_save_memory_node(state: TravelPlanState) -> dict[str, Any]:
    trip_plan = TripPlan.model_validate(state["trip_plan"])
    existing_candidates = list(state.get("memory_candidates", []))
    extracted = MemoryExtractionService().extract_from_final_plan(
        trip_plan=trip_plan,
        working_messages=state.get("working_messages", []),
        tool_observations=state.get("tool_observations", []),
        existing_candidates=existing_candidates,
    )
    return {
        "memory_candidates": merge_memory_candidates(existing_candidates, extracted),
    }


def _business_validation_errors(trip_plan: TripPlan, state: TravelPlanState) -> list[str]:
    normalized = state.get("normalized_request")
    errors: list[str] = []

    if normalized is not None:
        if trip_plan.session_id != normalized.session_id:
            errors.append("session_id must match resolved session_id")
        if trip_plan.cities != normalized.cities:
            errors.append("cities must match normalized request cities")
        if trip_plan.start_date != normalized.start_date or trip_plan.end_date != normalized.end_date:
            errors.append("date range must match normalized request")

    for expected_index, day in enumerate(trip_plan.days):
        expected_date = trip_plan.start_date + timedelta(days=expected_index)
        if day.day_index != expected_index:
            errors.append(f"days[{expected_index}].day_index must be {expected_index}")
        if day.date != expected_date:
            errors.append(f"days[{expected_index}].date must be {expected_date.isoformat()}")
        for point_index, point in enumerate(day.map_points):
            if point.day_index is not None and point.day_index != day.day_index:
                errors.append(
                    f"days[{expected_index}].map_points[{point_index}].day_index must match day_index"
                )
        if _has_located_entities(day) and not day.map_points:
            errors.append(f"days[{expected_index}].map_points must include anchors for located entities")
        if normalized is not None:
            max_attractions = _max_attractions_per_day(normalized)
            if len(day.attractions) > max_attractions:
                errors.append(
                    f"days[{expected_index}].attractions must not include more than "
                    f"{max_attractions} attractions for this trip pace"
                )

    return errors


def _memory_recall_query(request: Any) -> str:
    preferences = request.preferences
    return " ".join(
        [
            request.user_id,
            " ".join(request.cities),
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            "transport",
            preferences.transport_preference.value_en,
            "accommodation",
            " ".join(preference.value_en for preference in preferences.accommodation_preference),
            "attractions",
            " ".join(preference.value_en for preference in preferences.attraction_preference),
            "budget",
            str(request.budget or ""),
            request.extra_requirements or "",
        ]
    )


def _has_located_entities(day: DayPlan) -> bool:
    return (
        any(attraction.location is not None for attraction in day.attractions)
        or day.hotel is not None
        and day.hotel.location is not None
        or any(meal.location is not None for meal in day.meals)
    )


def _maintain_tool_observation(
    observations: list[Any],
    observation: Any,
    memory_candidates: list[MemoryCandidate],
) -> tuple[list[Any], list[MemoryCandidate]]:
    result = maintain_tool_observations(
        observations,
        observation,
        extraction_service=MemoryExtractionService(),
        existing_candidates=memory_candidates,
    )
    return result.retained_messages, merge_memory_candidates(memory_candidates, result.extracted_candidates)
