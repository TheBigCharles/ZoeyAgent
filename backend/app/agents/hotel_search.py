"""LLM-driven bounded ReAct-style hotel search subgraph."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.context import SpecialistContextBuilder
from app.agents.working_memory import maintain_tool_observations, merge_memory_candidates
from app.config import exception_details
from app.memory.extraction import MemoryExtractionService
from app.schemas.domain import Attraction, Hotel
from app.schemas.graph import HotelSearchResult, SearchQuality, TravelPlanState
from app.services.llm_service import validate_structured_output


HOTEL_TOOL_NAME = "search_hotels"


class HotelSearchPlanStep(BaseModel):
    city: str
    anchor: str = ""
    intent: str
    suggested_keywords: list[str] = Field(default_factory=list)


class HotelSearchPlan(BaseModel):
    steps: list[HotelSearchPlanStep] = Field(default_factory=list)


class HotelSearchAction(BaseModel):
    tool_name: Literal["search_hotels"]
    keywords: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    anchor: str = ""
    rationale: str = ""


class HotelSearchLocalState(BaseModel):
    local_plan: HotelSearchPlan = Field(default_factory=HotelSearchPlan)
    attempted_keywords: list[str] = Field(default_factory=list)
    attempted_anchors: list[str] = Field(default_factory=list)
    local_observations: list[str] = Field(default_factory=list)
    partial_candidates: list[Hotel] = Field(default_factory=list)
    ranking_reasons: list[str] = Field(default_factory=list)
    quality: SearchQuality | None = None
    retry_count: int = 0


def make_hotel_search_node(
    amap_client: Any | None = None,
    llm_service: Any | None = None,
    context_builder: SpecialistContextBuilder | None = None,
    max_retries: int = 2,
    route_summary_timeout_seconds: float = 5.0,
    max_route_summary_candidates: int = 1,
):
    async def hotel_search_node(state: TravelPlanState) -> dict[str, Any]:
        observations = list(state.get("tool_observations", []))
        if amap_client is None or llm_service is None:
            result = _empty_result("Hotel search skipped because amap_client or llm_service is unavailable.")
            return _write_back(result, state)

        local_state = HotelSearchLocalState()
        builder = context_builder or SpecialistContextBuilder()
        try:
            local_state.local_plan = await _create_plan(llm_service, state, builder)
        except Exception as exc:
            result = _empty_result(
                "Hotel search LLM plan failed.",
                details=exception_details(exc),
            )
            return _write_back(result, state)

        attempts = max_retries + 1
        for attempt in range(1, attempts + 1):
            local_state.retry_count = attempt - 1
            try:
                action = await _choose_action(llm_service, state, local_state, builder)
            except Exception as exc:
                local_state.quality = SearchQuality(
                    enough_results=False,
                    result_count=len(local_state.partial_candidates),
                    reason="LLM action failed",
                    retry_suggested=False,
                )
                local_state.local_observations.append(f"Hotel search LLM action failed: {type(exc).__name__}.")
                break

            local_state.attempted_keywords.append(action.keywords)
            if action.anchor:
                local_state.attempted_anchors.append(action.anchor)
            local_state.local_observations.append(
                f"LLM action {action.tool_name}: city={action.city}, keywords={action.keywords}, "
                f"anchor={action.anchor}, rationale={action.rationale}"
            )

            try:
                candidates = await amap_client.search_hotels(action.keywords, city=action.city)
            except Exception as exc:
                local_state.quality = SearchQuality(
                    enough_results=False,
                    result_count=len(local_state.partial_candidates),
                    reason=f"Amap hotel search failed: {type(exc).__name__}",
                    retry_suggested=attempt < attempts,
                )
                local_state.local_observations.append(
                    f"Hotel search tool failure for {action.city}/{action.keywords}: {type(exc).__name__}."
                )
                if attempt >= attempts:
                    break
                local_state.local_observations.append(f"quality warning: {local_state.quality.reason}")
                continue

            new_candidates = _deduplicate(candidates)
            route_candidates = await _maybe_enrich_route_summaries(
                amap_client=amap_client,
                state=state,
                hotels=new_candidates,
                observations=local_state.local_observations,
                timeout_seconds=route_summary_timeout_seconds,
                max_candidates=max_route_summary_candidates,
            )
            local_state.partial_candidates = _rank_hotels(
                _deduplicate([*local_state.partial_candidates, *route_candidates]),
                state,
            )
            local_state.ranking_reasons = _ranking_reasons(local_state.partial_candidates, state)
            local_state.quality = _evaluate_quality(local_state.partial_candidates, state)
            local_state.local_observations.append(
                f"Hotel search returned {len(new_candidates)} candidates for "
                f"{action.city}/{action.keywords}; retained {len(local_state.partial_candidates)} unique candidates."
            )

            if local_state.quality.enough_results:
                break
            local_state.local_observations.append(f"quality warning: {local_state.quality.reason}")
            if attempt >= attempts:
                break

        final_quality = local_state.quality or SearchQuality(
            enough_results=False,
            result_count=0,
            reason="Hotel search did not execute a valid action",
            retry_suggested=False,
        )
        if not final_quality.enough_results:
            local_state.local_observations.append(f"Hotel search quality warning: {final_quality.reason}")

        candidates = local_state.partial_candidates
        result = HotelSearchResult(
            selected_hotel=candidates[0] if candidates else None,
            candidate_hotels=candidates,
            search_areas=list(dict.fromkeys(local_state.attempted_anchors)),
            ranking_reasons=local_state.ranking_reasons,
            step_observations=local_state.local_observations,
            quality=final_quality,
        )
        return _write_back(result, state)

    return hotel_search_node


async def _create_plan(
    llm_service: Any,
    state: TravelPlanState,
    context_builder: SpecialistContextBuilder,
) -> HotelSearchPlan:
    messages = context_builder.build_messages(
        purpose="hotel_search_plan",
        state=state,
        local_state=None,
        output_schema_name="HotelSearchPlan",
        instruction=(
            "你是旅行酒店搜索子图的本地任务规划器。只返回 JSON。"
            "不要生成最终行程，不要写长期记忆，不要确认真实房态。"
            "请基于城市、预算、住宿偏好、交通方式和已找到的景点 anchor 生成局部酒店搜索 plan。"
            "JSON 形状为 "
            '{"steps":[{"city":"...","anchor":"...","intent":"...","suggested_keywords":["..."]}]}。'
        ),
    )
    return await _complete_structured(llm_service, messages, HotelSearchPlan)


async def _choose_action(
    llm_service: Any,
    state: TravelPlanState,
    local_state: HotelSearchLocalState,
    context_builder: SpecialistContextBuilder,
) -> HotelSearchAction:
    messages = context_builder.build_messages(
        purpose="hotel_search_action",
        state=state,
        local_state=local_state,
        output_schema_name="HotelSearchAction",
        instruction=(
            "你是酒店搜索 ReAct executor。只返回 JSON。"
            "你只能选择 tool_name='search_hotels'。"
            "不要返回 raw provider response，不要生成 TripPlan，不要承诺真实房态。"
            "根据局部 plan、景点 anchor、已有 observation 和 quality warning 选择下一次 action。"
            "JSON 形状必须为 "
            '{"tool_name":"search_hotels","keywords":"...","city":"...","anchor":"...","rationale":"..."}。'
        ),
    )
    return await _complete_structured(llm_service, messages, HotelSearchAction)


async def _complete_structured(llm_service: Any, messages: list[dict[str, str]], schema: type[BaseModel]) -> Any:
    response = await llm_service.complete(messages, temperature=0)
    return validate_structured_output(response, schema)


def _evaluate_quality(candidates: list[Hotel], state: TravelPlanState) -> SearchQuality:
    normalized = state["normalized_request"]
    needed_count = min(max(len(normalized.cities) * 2, 2), 4)
    map_ready_count = sum(1 for candidate in candidates if candidate.location is not None)
    budget_fit_count = sum(1 for candidate in candidates if _fits_budget(candidate, state))
    enough_results = len(candidates) >= needed_count and map_ready_count > 0 and budget_fit_count > 0
    reason = (
        f"enough hotel candidates: {len(candidates)} total, {map_ready_count} map-ready, "
        f"{budget_fit_count} budget-fit"
        if enough_results
        else f"need at least {needed_count} hotel candidates, one map-ready candidate, and one budget-fit candidate; "
        f"got {len(candidates)} total, {map_ready_count} map-ready, {budget_fit_count} budget-fit"
    )
    return SearchQuality(
        enough_results=enough_results,
        result_count=len(candidates),
        reason=reason,
        retry_suggested=not enough_results,
        next_keywords=_fallback_keywords(normalized.accommodation_preferences),
    )


def _fallback_keywords(preferences: list[str]) -> list[str]:
    mapping = {
        "budget_hotel": ["经济型酒店", "快捷酒店"],
        "mid_level_hotel": ["舒适型酒店", "高评分酒店"],
        "five_star_hotel": ["五星级酒店", "豪华酒店"],
    }
    keywords: list[str] = []
    for preference in preferences:
        keywords.extend(mapping.get(preference, []))
    return keywords or ["酒店"]


def _empty_result(reason: str, details: dict[str, Any] | None = None) -> HotelSearchResult:
    detail_suffix = f" {details}" if details else ""
    return HotelSearchResult(
        selected_hotel=None,
        candidate_hotels=[],
        search_areas=[],
        ranking_reasons=[],
        step_observations=[f"{reason}{detail_suffix}"],
        quality=SearchQuality(
            enough_results=False,
            result_count=0,
            reason=reason,
            retry_suggested=False,
        ),
    )


def _write_back(result: HotelSearchResult, state: TravelPlanState) -> dict[str, Any]:
    observations = list(state.get("tool_observations", []))
    memory_candidates = list(state.get("memory_candidates", []))
    for observation in result.step_observations:
        maintenance = maintain_tool_observations(
            observations,
            observation,
            extraction_service=MemoryExtractionService(),
            existing_candidates=memory_candidates,
        )
        observations = maintenance.retained_messages
        memory_candidates = merge_memory_candidates(memory_candidates, maintenance.extracted_candidates)
    return {
        "hotel_search_result": result,
        "hotels": result.candidate_hotels,
        "tool_observations": observations,
        "memory_candidates": memory_candidates,
    }


def _deduplicate(hotels: list[Hotel]) -> list[Hotel]:
    seen: set[str] = set()
    deduplicated: list[Hotel] = []
    for hotel in hotels:
        key = _hotel_key(hotel)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(hotel)
    return deduplicated


def _hotel_key(hotel: Hotel) -> str:
    if hotel.poi_id:
        return f"poi:{hotel.poi_id}"
    return f"name:{hotel.city or ''}:{hotel.name}:{hotel.address}"


def _rank_hotels(hotels: list[Hotel], state: TravelPlanState) -> list[Hotel]:
    return sorted(
        hotels,
        key=lambda item: (
            item.location is None,
            not _fits_budget(item, state),
            item.estimated_travel_time_minutes is None,
            item.estimated_travel_time_minutes if item.estimated_travel_time_minutes is not None else 9999,
            -(item.rating if item.rating is not None else -1),
            item.poi_id is None,
        ),
    )


def _ranking_reasons(hotels: list[Hotel], state: TravelPlanState) -> list[str]:
    reasons: list[str] = []
    for hotel in hotels[:5]:
        parts = []
        parts.append("map-ready" if hotel.location is not None else "missing coordinates")
        parts.append("budget-fit" if _fits_budget(hotel, state) else "outside budget signal")
        if hotel.estimated_travel_time_minutes is not None:
            parts.append(f"{hotel.estimated_travel_time_minutes} min to anchor")
        if hotel.rating is not None:
            parts.append(f"rating {hotel.rating}")
        reasons.append(f"{hotel.name}: {', '.join(parts)}")
    return reasons


def _fits_budget(hotel: Hotel, state: TravelPlanState) -> bool:
    budget = state["normalized_request"].budget
    if budget is None or hotel.estimated_cost == 0:
        return True
    nights = max(state["normalized_request"].days_count - 1, 1)
    per_night_budget = budget / nights
    return hotel.estimated_cost <= per_night_budget


async def _maybe_enrich_route_summaries(
    *,
    amap_client: Any,
    state: TravelPlanState,
    hotels: list[Hotel],
    observations: list[str],
    timeout_seconds: float,
    max_candidates: int,
) -> list[Hotel]:
    if not hasattr(amap_client, "get_route_summary"):
        return hotels

    anchor = _first_anchor(state)
    if anchor is None:
        return hotels

    enriched: list[Hotel] = []
    mode = _route_mode(state["normalized_request"].transport_preference)
    for index, hotel in enumerate(hotels):
        if index >= max_candidates:
            enriched.append(hotel)
            continue
        if not (hotel.address or hotel.name):
            enriched.append(hotel)
            continue
        try:
            summary = await asyncio.wait_for(
                amap_client.get_route_summary(
                    origin_address=hotel.address or hotel.name,
                    destination_address=anchor.address or anchor.name,
                    mode=mode,
                    origin_city=hotel.city,
                    destination_city=anchor.city,
                ),
                timeout=timeout_seconds,
            )
        except Exception as exc:
            observations.append(f"Hotel route summary failed for {hotel.name}: {type(exc).__name__}.")
            enriched.append(hotel)
            continue
        enriched.append(
            hotel.model_copy(
                update={
                    "distance_to_main_area_km": summary.get("route_distance_km"),
                    "estimated_travel_time_minutes": summary.get("route_duration_minutes"),
                    "transit_method": summary.get("transit_method"),
                }
            )
        )
    return enriched


def _first_anchor(state: TravelPlanState) -> Attraction | None:
    for attraction in state.get("attractions", []):
        if attraction.address or attraction.name:
            return attraction
    return None


def _route_mode(transport_preference: str) -> Literal["walking", "driving", "transit"]:
    if transport_preference == "driving":
        return "driving"
    return "transit"
