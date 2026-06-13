"""LLM-driven bounded ReAct-style attraction search subgraph."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.context import SpecialistContextBuilder
from app.config import exception_details
from app.schemas.domain import Attraction
from app.schemas.graph import AttractionSearchResult, SearchQuality, TravelPlanState
from app.services.llm_service import validate_structured_output


ATTRACTION_TOOL_NAME = "search_attractions"


class AttractionSearchPlanStep(BaseModel):
    city: str
    intent: str
    suggested_keywords: list[str] = Field(default_factory=list)


class AttractionSearchPlan(BaseModel):
    steps: list[AttractionSearchPlanStep] = Field(default_factory=list)


class AttractionSearchAction(BaseModel):
    tool_name: Literal["search_attractions"]
    keywords: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    rationale: str = ""


class AttractionSearchLocalState(BaseModel):
    local_plan: AttractionSearchPlan = Field(default_factory=AttractionSearchPlan)
    attempted_keywords: list[str] = Field(default_factory=list)
    local_observations: list[str] = Field(default_factory=list)
    partial_candidates: list[Attraction] = Field(default_factory=list)
    quality: SearchQuality | None = None
    retry_count: int = 0


def make_attraction_search_node(
    amap_client: Any | None = None,
    llm_service: Any | None = None,
    context_builder: SpecialistContextBuilder | None = None,
    max_retries: int = 2,
):
    async def attraction_search_node(state: TravelPlanState) -> dict[str, Any]:
        observations = list(state.get("tool_observations", []))
        if amap_client is None or llm_service is None:
            result = _empty_result("Attraction search skipped because amap_client or llm_service is unavailable.")
            return _write_back(result, observations)

        local_state = AttractionSearchLocalState()
        builder = context_builder or SpecialistContextBuilder()
        try:
            local_state.local_plan = await _create_plan(llm_service, state, builder)
        except Exception as exc:
            result = _empty_result(
                "Attraction search LLM plan failed.",
                details=exception_details(exc),
            )
            return _write_back(result, observations)

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
                local_state.local_observations.append(
                    f"Attraction search LLM action failed: {type(exc).__name__}."
                )
                break

            local_state.attempted_keywords.append(action.keywords)
            local_state.local_observations.append(
                f"LLM action {action.tool_name}: city={action.city}, keywords={action.keywords}, "
                f"rationale={action.rationale}"
            )

            try:
                candidates = await amap_client.search_attractions(action.keywords, city=action.city)
            except Exception as exc:
                local_state.quality = SearchQuality(
                    enough_results=False,
                    result_count=len(local_state.partial_candidates),
                    reason=f"Amap attraction search failed: {type(exc).__name__}",
                    retry_suggested=attempt < attempts,
                )
                local_state.local_observations.append(
                    f"Attraction search tool failure for {action.city}/{action.keywords}: {type(exc).__name__}."
                )
                if attempt >= attempts:
                    break
                local_state.local_observations.append(f"quality warning: {local_state.quality.reason}")
                continue

            new_candidates = _deduplicate(candidates)
            local_state.partial_candidates = _rank_attractions(
                _deduplicate([*local_state.partial_candidates, *new_candidates])
            )
            local_state.quality = _evaluate_quality(local_state.partial_candidates, state)
            local_state.local_observations.append(
                f"Attraction search returned {len(new_candidates)} candidates for "
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
            reason="Attraction search did not execute a valid action",
            retry_suggested=False,
        )
        if not final_quality.enough_results:
            local_state.local_observations.append(f"Attraction search quality warning: {final_quality.reason}")

        result = AttractionSearchResult(
            attractions=local_state.partial_candidates,
            search_keywords=list(dict.fromkeys(local_state.attempted_keywords)),
            step_observations=local_state.local_observations,
            quality=final_quality,
        )
        return _write_back(result, observations)

    return attraction_search_node


async def _create_plan(
    llm_service: Any,
    state: TravelPlanState,
    context_builder: SpecialistContextBuilder,
) -> AttractionSearchPlan:
    messages = context_builder.build_messages(
        purpose="attraction_search_plan",
        state=state,
        local_state=None,
        output_schema_name="AttractionSearchPlan",
        instruction=(
            "你是旅行景点搜索子图的本地任务规划器。只返回 JSON。"
            "不要生成最终行程，不要写长期记忆。"
            "请为景点搜索生成局部 plan，JSON 形状为 "
            '{"steps":[{"city":"...","intent":"...","suggested_keywords":["..."]}]}。'
        ),
    )
    return await _complete_structured(llm_service, messages, AttractionSearchPlan)


async def _choose_action(
    llm_service: Any,
    state: TravelPlanState,
    local_state: AttractionSearchLocalState,
    context_builder: SpecialistContextBuilder,
) -> AttractionSearchAction:
    messages = context_builder.build_messages(
        purpose="attraction_search_action",
        state=state,
        local_state=local_state,
        output_schema_name="AttractionSearchAction",
        instruction=(
            "你是景点搜索 ReAct executor。只返回 JSON。"
            "你只能选择 tool_name='search_attractions'。"
            "不要返回 raw provider response，不要生成 TripPlan。"
            "根据局部 plan、已有 observation 和 quality warning 选择下一次 action。"
            "JSON 形状必须为 "
            '{"tool_name":"search_attractions","keywords":"...","city":"...","rationale":"..."}。'
        ),
    )
    return await _complete_structured(llm_service, messages, AttractionSearchAction)


async def _complete_structured(llm_service: Any, messages: list[dict[str, str]], schema: type[BaseModel]) -> Any:
    response = await llm_service.complete(messages, temperature=0)
    return validate_structured_output(response, schema)


def _evaluate_quality(candidates: list[Attraction], state: TravelPlanState) -> SearchQuality:
    normalized = state["normalized_request"]
    needed_count = min(normalized.days_count * 2, 6)
    map_ready_count = sum(1 for candidate in candidates if candidate.location is not None)
    enough_results = len(candidates) >= needed_count and map_ready_count > 0
    reason = (
        f"enough candidates: {len(candidates)} total, {map_ready_count} map-ready"
        if enough_results
        else f"need at least {needed_count} candidates and one map-ready candidate; "
        f"got {len(candidates)} total and {map_ready_count} map-ready"
    )
    return SearchQuality(
        enough_results=enough_results,
        result_count=len(candidates),
        reason=reason,
        retry_suggested=not enough_results,
        next_keywords=_fallback_keywords(normalized.attraction_preferences),
    )


def _fallback_keywords(preferences: list[str]) -> list[str]:
    mapping = {
        "history_culture": ["博物馆", "古迹", "历史文化"],
        "nature": ["自然风光", "公园"],
        "food": ["美食街", "特色美食"],
        "shopping": ["购物中心", "商业街"],
        "art": ["美术馆", "艺术馆"],
        "leisure": ["休闲娱乐", "景区"],
    }
    keywords: list[str] = []
    for preference in preferences:
        keywords.extend(mapping.get(preference, []))
    return keywords or ["景点"]


def _empty_result(reason: str, details: dict[str, Any] | None = None) -> AttractionSearchResult:
    detail_suffix = f" {details}" if details else ""
    return AttractionSearchResult(
        attractions=[],
        search_keywords=[],
        step_observations=[f"{reason}{detail_suffix}"],
        quality=SearchQuality(
            enough_results=False,
            result_count=0,
            reason=reason,
            retry_suggested=False,
        ),
    )


def _write_back(result: AttractionSearchResult, existing_observations: list[Any]) -> dict[str, Any]:
    return {
        "attraction_search_result": result,
        "attractions": result.attractions,
        "tool_observations": [*existing_observations, *result.step_observations],
    }


def _deduplicate(attractions: list[Attraction]) -> list[Attraction]:
    seen: set[str] = set()
    deduplicated: list[Attraction] = []
    for attraction in attractions:
        key = _attraction_key(attraction)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(attraction)
    return deduplicated


def _attraction_key(attraction: Attraction) -> str:
    if attraction.poi_id:
        return f"poi:{attraction.poi_id}"
    return f"name:{attraction.city or ''}:{attraction.name}:{attraction.address}"


def _rank_attractions(attractions: list[Attraction]) -> list[Attraction]:
    return sorted(
        attractions,
        key=lambda item: (
            item.location is None,
            -(item.rating if item.rating is not None else -1),
            item.poi_id is None,
        ),
    )
