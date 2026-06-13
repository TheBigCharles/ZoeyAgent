import asyncio

import pytest

from app.agents.specialist import (
    RestrictedToolExecutor,
    SpecialistSearchRunner,
    SpecialistSearchStep,
)
from app.config import StructuredAppError, TOOL_CALL_FAILED
from app.schemas.domain import Attraction
from app.schemas.graph import AttractionSearchResult, SearchQuality, SpecialistSearchConfig, TravelPlanState


def make_config(max_retries: int = 2) -> SpecialistSearchConfig:
    return SpecialistSearchConfig(
        name="attraction",
        planner_prompt="AttractionTaskPlannerPrompt",
        executor_prompt="AttractionStepExecutorPrompt",
        evaluator_prompt="AttractionStepEvaluatorPrompt",
        allowed_tools=["maps_text_search"],
        output_schema_name="AttractionSearchResult",
        ranking_policy="name_deduplicate",
        max_retries=max_retries,
    )


def make_step() -> SpecialistSearchStep:
    return SpecialistSearchStep(
        name="search-history",
        tool_name="maps_text_search",
        arguments={"keywords": "history", "city": "Beijing"},
        description="Search history attractions in Beijing",
    )


def attraction_result_factory(
    candidates: list[Attraction],
    observations: list[str],
    quality: SearchQuality,
) -> AttractionSearchResult:
    return AttractionSearchResult(
        attractions=candidates,
        search_keywords=["history"],
        step_observations=observations,
        quality=quality,
    )


def attraction_write_back(result: AttractionSearchResult) -> dict:
    return {
        "attraction_search_result": result,
        "attractions": result.attractions,
        "tool_observations": result.step_observations,
    }


def test_restricted_tool_executor_rejects_tools_not_allowed_by_config() -> None:
    calls: list[str] = []

    async def weather_tool(**_: object) -> list[Attraction]:
        calls.append("weather")
        return []

    async def run_executor() -> None:
        executor = RestrictedToolExecutor({"maps_weather": weather_tool})
        await executor.execute(
            SpecialistSearchStep(name="bad-step", tool_name="maps_weather"),
            allowed_tools=["maps_text_search"],
        )

    with pytest.raises(StructuredAppError) as error:
        asyncio.run(run_executor())

    assert error.value.code == TOOL_CALL_FAILED
    assert calls == []


def test_specialist_runner_retries_low_quality_step_then_writes_ranked_result() -> None:
    calls: list[dict] = []

    async def text_search(**arguments: object) -> list[Attraction]:
        calls.append(arguments)
        if len(calls) == 1:
            return []
        return [
            Attraction(name="Forbidden City", city="Beijing", poi_id="poi-1"),
            Attraction(name="Forbidden City", city="Beijing", poi_id="poi-1"),
            Attraction(name="Summer Palace", city="Beijing", poi_id="poi-2"),
        ]

    def evaluate(candidates: list[Attraction], attempt: int) -> SearchQuality:
        enough = len(candidates) >= 2
        return SearchQuality(
            enough_results=enough,
            result_count=len(candidates),
            reason="enough candidates" if enough else "too few candidates",
            retry_suggested=not enough,
            next_keywords=["museum"] if not enough else [],
        )

    async def run_runner() -> TravelPlanState:
        runner = SpecialistSearchRunner(
            config=make_config(max_retries=2),
            plan_steps=lambda _: [make_step()],
            tool_executor=RestrictedToolExecutor({"maps_text_search": text_search}),
            evaluate_step=evaluate,
            result_factory=attraction_result_factory,
            write_back=attraction_write_back,
            deduplicate_key=lambda attraction: attraction.poi_id or attraction.name,
        )
        return await runner.run({})

    result = asyncio.run(run_runner())

    search_result = result["attraction_search_result"]
    assert len(calls) == 2
    assert [item.name for item in search_result.attractions] == ["Forbidden City", "Summer Palace"]
    assert search_result.quality.enough_results is True
    assert "attraction search-history attempt 1 returned 0 candidates: too few candidates" in result[
        "tool_observations"
    ]
    assert "attraction search-history attempt 2 returned 2 candidates: enough candidates" in result[
        "tool_observations"
    ]


def test_specialist_runner_returns_best_effort_quality_warning_after_retry_limit() -> None:
    async def text_search(**_: object) -> list[Attraction]:
        return []

    def evaluate(candidates: list[Attraction], attempt: int) -> SearchQuality:
        return SearchQuality(
            enough_results=False,
            result_count=len(candidates),
            reason=f"attempt {attempt} still has too few candidates",
            retry_suggested=True,
            next_keywords=["park"],
        )

    async def run_runner() -> TravelPlanState:
        runner = SpecialistSearchRunner(
            config=make_config(max_retries=1),
            plan_steps=lambda _: [make_step()],
            tool_executor=RestrictedToolExecutor({"maps_text_search": text_search}),
            evaluate_step=evaluate,
            result_factory=attraction_result_factory,
            write_back=attraction_write_back,
            deduplicate_key=lambda attraction: attraction.poi_id or attraction.name,
        )
        return await runner.run({})

    result = asyncio.run(run_runner())

    search_result = result["attraction_search_result"]
    assert search_result.attractions == []
    assert search_result.quality.enough_results is False
    assert search_result.quality.reason == "attempt 2 still has too few candidates"
    assert "attraction quality warning: attempt 2 still has too few candidates" in result["tool_observations"]
