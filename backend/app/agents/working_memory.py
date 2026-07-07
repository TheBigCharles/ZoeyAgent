"""Short-term working memory helpers for a planning session."""

from __future__ import annotations

from typing import Any

from app.schemas.memory import MemoryCandidate, WorkingMemoryMaintenanceResult

MAX_WORKING_MEMORY_ITEMS = 50


def merge_memory_candidates(
    existing: list[MemoryCandidate] | None,
    new_candidates: list[MemoryCandidate] | None,
) -> list[MemoryCandidate]:
    seen = {(candidate.target, " ".join(candidate.text.casefold().split())) for candidate in existing or []}
    merged = list(existing or [])
    for candidate in new_candidates or []:
        key = (candidate.target, " ".join(candidate.text.casefold().split()))
        if key in seen:
            continue
        seen.add(key)
        merged.append(candidate)
    return merged


def maintain_working_messages(
    messages: list[dict[str, Any]] | None,
    message: dict[str, Any],
    *,
    extraction_service: Any | None = None,
    existing_candidates: list[MemoryCandidate] | None = None,
) -> WorkingMemoryMaintenanceResult:
    return _maintain([*(messages or []), message], "working_messages_overflow", extraction_service, existing_candidates)


def maintain_tool_observations(
    observations: list[Any] | None,
    observation: Any | None,
    *,
    extraction_service: Any | None = None,
    existing_candidates: list[MemoryCandidate] | None = None,
) -> WorkingMemoryMaintenanceResult:
    values = list(observations or [])
    if observation is not None:
        values.append(observation)
    return _maintain(values, "tool_observations_overflow", extraction_service, existing_candidates)


def _maintain(
    values: list[Any],
    source: str,
    extraction_service: Any | None,
    existing_candidates: list[MemoryCandidate] | None,
) -> WorkingMemoryMaintenanceResult:
    overflow = values[:-MAX_WORKING_MEMORY_ITEMS]
    retained = values[-MAX_WORKING_MEMORY_ITEMS:]
    candidates: list[MemoryCandidate] = []
    if overflow and extraction_service is not None:
        extracted = extraction_service.extract_from_overflow(
            source=source,
            items=overflow,
            existing_candidates=existing_candidates,
        )
        candidates = [candidate for candidate in extracted if candidate.target != "discard"]
    return WorkingMemoryMaintenanceResult(
        retained_messages=retained,
        extracted_candidates=candidates,
        dropped_count=len(overflow),
    )
