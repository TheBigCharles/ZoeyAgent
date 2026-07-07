from app.memory.extraction import MemoryExtractionService
from app.schemas.domain import DayPlan, Hotel
from app.schemas.memory import MemoryCandidate
from app.schemas.trip import TripPlan


def test_memory_extraction_classifies_overflow_preferences_and_discards_noise() -> None:
    service = MemoryExtractionService()

    candidates = service.extract_from_overflow(
        source="working_messages_overflow",
        items=[
            {"role": "user", "content": "我喜欢轻松节奏，不要太赶。"},
            "Amap weather query for 北京 returned 4 records.",
        ],
    )

    assert any(candidate.target == "semantic" and "轻松节奏" in candidate.text for candidate in candidates)
    assert any(candidate.target == "discard" and "Amap weather query" in candidate.text for candidate in candidates)


def test_memory_extraction_deduplicates_and_filters_low_confidence_candidates() -> None:
    service = MemoryExtractionService(min_confidence=0.6)
    existing = [
        MemoryCandidate(
            target="semantic",
            text="用户偏好轻松节奏",
            reason="existing",
            confidence=0.9,
        )
    ]

    candidates = service.filter_candidates(
        [
            MemoryCandidate(
                target="semantic",
                text="用户偏好轻松节奏",
                reason="duplicate",
                confidence=0.9,
            ),
            MemoryCandidate(
                target="episodic",
                text="用户确认了北京行程",
                reason="valid final plan",
                confidence=0.8,
            ),
            MemoryCandidate(
                target="semantic",
                text="低置信度偏好",
                reason="weak signal",
                confidence=0.4,
            ),
        ],
        existing_candidates=existing,
    )

    assert [candidate.text for candidate in candidates] == ["用户确认了北京行程"]


def test_memory_extraction_extracts_episodic_candidate_from_valid_trip_plan() -> None:
    service = MemoryExtractionService()
    trip_plan = TripPlan(
        session_id="session-memory-001",
        cities=["北京"],
        start_date="2026-07-10",
        end_date="2026-07-10",
        days=[
            DayPlan(
                date="2026-07-10",
                day_index=0,
                city="北京",
                description="参观故宫。",
                transportation="public_transport",
                accommodation="budget_hotel",
                hotel=Hotel(name="王府井酒店", city="北京"),
                total_price=500,
            )
        ],
        overall_suggestions="轻松游玩。",
    )

    candidates = service.extract_from_final_plan(
        trip_plan=trip_plan,
        working_messages=[{"role": "user", "content": "我喜欢历史文化景点。"}],
        tool_observations=["Amap search returned 18 POIs."],
    )

    assert any(candidate.target == "semantic" and "历史文化" in candidate.text for candidate in candidates)
    assert any(candidate.target == "episodic" and "北京" in candidate.text for candidate in candidates)
    assert all("Amap search returned" not in candidate.text for candidate in candidates if candidate.target != "discard")
