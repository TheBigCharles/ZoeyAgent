"""Shared specialist search subgraph infrastructure.

This module provides the narrow Plan-and-Solve loop used by future attraction
and hotel specialist subgraphs. Domain-specific code supplies planning,
evaluation, ranking, result construction, and state write-back.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.config import StructuredAppError, TOOL_CALL_FAILED, exception_details
from app.schemas.graph import SearchQuality, SpecialistSearchConfig, TravelPlanState


Candidate = TypeVar("Candidate")
Result = TypeVar("Result")


class SpecialistSearchStep(BaseModel):
    name: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class RestrictedToolExecutor:
    def __init__(self, tools: dict[str, Callable[..., Any]]) -> None:
        self._tools = tools

    async def execute(self, step: SpecialistSearchStep, allowed_tools: list[str]) -> Any:
        if step.tool_name not in allowed_tools:
            raise StructuredAppError(
                code=TOOL_CALL_FAILED,
                message="Specialist step attempted to call a tool outside its allowlist",
                details={"tool": step.tool_name, "allowed_tools": allowed_tools, "step": step.name},
            )
        try:
            tool = self._tools[step.tool_name]
        except KeyError as exc:
            raise StructuredAppError(
                code=TOOL_CALL_FAILED,
                message="Specialist step requested an unregistered tool",
                details={"tool": step.tool_name, "step": step.name},
            ) from exc

        try:
            result = tool(**step.arguments)
            if inspect.isawaitable(result):
                return await result
            return result
        except StructuredAppError:
            raise
        except Exception as exc:
            raise StructuredAppError(
                code=TOOL_CALL_FAILED,
                message="Specialist tool execution failed",
                details={"tool": step.tool_name, "step": step.name, **exception_details(exc)},
            ) from exc


PlanSteps = Callable[[TravelPlanState], list[SpecialistSearchStep] | Awaitable[list[SpecialistSearchStep]]]
EvaluateStep = Callable[[list[Candidate], int], SearchQuality]
ResultFactory = Callable[[list[Candidate], list[str], SearchQuality], Result]
WriteBack = Callable[[Result], dict[str, Any]]
CandidateKey = Callable[[Candidate], Any]
RankCandidates = Callable[[list[Candidate]], list[Candidate]]


class SpecialistSearchRunner(Generic[Candidate, Result]):
    def __init__(
        self,
        *,
        config: SpecialistSearchConfig,
        plan_steps: PlanSteps,
        tool_executor: RestrictedToolExecutor,
        evaluate_step: EvaluateStep[Candidate],
        result_factory: ResultFactory[Candidate, Result],
        write_back: WriteBack[Result],
        deduplicate_key: CandidateKey[Candidate],
        rank_candidates: RankCandidates[Candidate] | None = None,
    ) -> None:
        self.config = config
        self.plan_steps = plan_steps
        self.tool_executor = tool_executor
        self.evaluate_step = evaluate_step
        self.result_factory = result_factory
        self.write_back = write_back
        self.deduplicate_key = deduplicate_key
        self.rank_candidates = rank_candidates or (lambda candidates: candidates)

    async def run(self, state: TravelPlanState) -> dict[str, Any]:
        steps = await self._plan(state)
        observations: list[str] = []
        candidates: list[Candidate] = []
        last_quality = SearchQuality(enough_results=False, reason="no specialist search steps were planned")

        for step in steps:
            step_candidates, step_observations, last_quality = await self._run_step(step)
            candidates.extend(step_candidates)
            observations.extend(step_observations)

        final_candidates = self.rank_candidates(_deduplicate(candidates, self.deduplicate_key))
        if final_candidates and not last_quality.enough_results:
            last_quality = last_quality.model_copy(update={"result_count": len(final_candidates)})

        if not last_quality.enough_results:
            observations.append(f"{self.config.name} quality warning: {last_quality.reason}")

        result = self.result_factory(final_candidates, observations, last_quality)
        return self.write_back(result)

    async def _plan(self, state: TravelPlanState) -> list[SpecialistSearchStep]:
        steps = self.plan_steps(state)
        if inspect.isawaitable(steps):
            return await steps
        return steps

    async def _run_step(
        self,
        step: SpecialistSearchStep,
    ) -> tuple[list[Candidate], list[str], SearchQuality]:
        observations: list[str] = []
        best_candidates: list[Candidate] = []
        last_quality = SearchQuality(enough_results=False, reason="step was not executed")
        max_attempts = self.config.max_retries + 1

        for attempt in range(1, max_attempts + 1):
            raw_candidates = await self.tool_executor.execute(step, self.config.allowed_tools)
            step_candidates = _coerce_candidate_list(raw_candidates)
            step_candidates = _deduplicate(step_candidates, self.deduplicate_key)
            quality = self.evaluate_step(step_candidates, attempt)
            observations.append(
                f"{self.config.name} {step.name} attempt {attempt} returned "
                f"{len(step_candidates)} candidates: {quality.reason}"
            )

            if len(step_candidates) >= len(best_candidates):
                best_candidates = step_candidates
                last_quality = quality

            if quality.enough_results or not quality.retry_suggested:
                return step_candidates, observations, quality

        return best_candidates, observations, last_quality


def _coerce_candidate_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        candidates = value.get("candidates") or value.get("items") or value.get("results")
        if isinstance(candidates, list):
            return candidates
    return [value]


def _deduplicate(items: list[Candidate], key_fn: CandidateKey[Candidate]) -> list[Candidate]:
    seen: set[Any] = set()
    deduplicated: list[Candidate] = []
    for item in items:
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    return deduplicated
