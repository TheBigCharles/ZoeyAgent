"""Memory candidate extraction for working-memory overflow and final plans."""

from __future__ import annotations

from typing import Any

from app.schemas.memory import MemoryCandidate
from app.schemas.trip import TripPlan


class MemoryExtractionService:
    def __init__(self, min_confidence: float = 0.55) -> None:
        self.min_confidence = min_confidence

    def extract_from_overflow(
        self,
        *,
        source: str,
        items: list[Any],
        existing_candidates: list[MemoryCandidate] | None = None,
    ) -> list[MemoryCandidate]:
        candidates = [self._candidate_from_text(_item_text(item), source=source) for item in items]
        return self.filter_candidates(candidates, existing_candidates=existing_candidates)

    def extract_from_final_plan(
        self,
        *,
        trip_plan: TripPlan,
        working_messages: list[Any] | None = None,
        tool_observations: list[Any] | None = None,
        existing_candidates: list[MemoryCandidate] | None = None,
    ) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        for message in working_messages or []:
            candidates.append(self._candidate_from_text(_item_text(message), source="final_plan_working_memory"))

        for observation in tool_observations or []:
            candidates.append(self._candidate_from_text(_item_text(observation), source="final_plan_tool_observation"))

        hotel_names = [
            day.hotel.name
            for day in trip_plan.days
            if day.hotel is not None and day.hotel.name
        ]
        hotel_part = f"，推荐住宿：{hotel_names[0]}" if hotel_names else ""
        candidates.append(
            MemoryCandidate(
                target="episodic",
                text=(
                    f"用户完成了 {trip_plan.start_date.isoformat()} 至 {trip_plan.end_date.isoformat()} "
                    f"{'、'.join(trip_plan.cities)} 行程规划{hotel_part}"
                ),
                reason="Final TripPlan passed validation",
                confidence=0.82,
                metadata={
                    "source": "final_trip_plan",
                    "session_id": trip_plan.session_id,
                    "cities": trip_plan.cities,
                    "start_date": trip_plan.start_date.isoformat(),
                    "end_date": trip_plan.end_date.isoformat(),
                },
            )
        )
        return self.filter_candidates(candidates, existing_candidates=existing_candidates)

    def filter_candidates(
        self,
        candidates: list[MemoryCandidate],
        *,
        existing_candidates: list[MemoryCandidate] | None = None,
    ) -> list[MemoryCandidate]:
        seen = {_dedupe_key(candidate) for candidate in existing_candidates or []}
        filtered: list[MemoryCandidate] = []
        for candidate in candidates:
            if candidate.target != "discard" and candidate.confidence < self.min_confidence:
                continue
            key = _dedupe_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            filtered.append(candidate)
        return filtered

    def _candidate_from_text(self, text: str, *, source: str) -> MemoryCandidate:
        normalized = " ".join(text.split())
        if not normalized:
            return MemoryCandidate(
                target="discard",
                text="empty memory item",
                reason="Empty working memory item",
                confidence=1.0,
                metadata={"source": source},
            )

        semantic_text = _semantic_text(normalized)
        if semantic_text is not None:
            return MemoryCandidate(
                target="semantic",
                text=semantic_text,
                reason="Stable user preference detected",
                confidence=0.86,
                metadata={"source": source},
            )

        if _looks_like_tool_noise(normalized):
            return MemoryCandidate(
                target="discard",
                text=normalized,
                reason="Transient tool observation",
                confidence=0.95,
                metadata={"source": source},
            )

        if _looks_like_decision(normalized):
            return MemoryCandidate(
                target="episodic",
                text=normalized,
                reason="Concrete planning decision or event",
                confidence=0.7,
                metadata={"source": source},
            )

        return MemoryCandidate(
            target="discard",
            text=normalized,
            reason="No long-term value detected",
            confidence=0.8,
            metadata={"source": source},
        )


def _item_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("content") or item.get("text") or item)
    return str(item)


def _semantic_text(text: str) -> str | None:
    lowered = text.lower()
    if "轻松节奏" in text or "不要太赶" in text or "relaxed" in lowered:
        return "用户偏好轻松节奏"
    if "历史文化" in text or "history" in lowered or "culture" in lowered:
        return "用户偏好历史文化景点"
    if "budget" in lowered or "经济" in text or "低预算" in text:
        return "用户偏好预算友好的选择"
    return None


def _looks_like_tool_noise(text: str) -> bool:
    lowered = text.lower()
    return (
        "amap" in lowered
        or "returned" in lowered
        or "query" in lowered
        or "tool" in lowered
        or "failed" in lowered
        or "timeout" in lowered
    )


def _looks_like_decision(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in ["confirmed", "selected", "rejected", "changed", "完成", "选择", "拒绝"])


def _dedupe_key(candidate: MemoryCandidate) -> tuple[str, str]:
    return candidate.target, " ".join(candidate.text.casefold().split())
