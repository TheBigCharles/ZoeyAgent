"""Trip planning routes."""

from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter

from app.schemas.domain import DayPlan, Meal
from app.schemas.trip import TripPlan, TripPlanRequest

router = APIRouter(prefix="/api/trip", tags=["trip"])


@router.post("/plan", response_model=TripPlan)
async def create_trip_plan(request: TripPlanRequest) -> TripPlan:
    session_id = request.session_id or str(uuid4())
    days = []
    total_days = (request.end_date - request.start_date).days + 1

    for day_index in range(total_days):
        current_date = request.start_date + timedelta(days=day_index)
        city = request.cities[min(day_index, len(request.cities) - 1)]
        days.append(
            DayPlan(
                date=current_date,
                day_index=day_index,
                city=city,
                description=f"Mock itinerary for day {day_index + 1} in {city}.",
                transportation=request.preferences.transport_preference.value_en,
                accommodation=", ".join(
                    preference.value_en for preference in request.preferences.accommodation_preference
                ),
                meals=[
                    Meal(type="breakfast", name="Mock breakfast", city=city),
                    Meal(type="lunch", name="Mock lunch", city=city),
                    Meal(type="dinner", name="Mock dinner", city=city),
                ],
                total_price=0,
            )
        )

    return TripPlan(
        session_id=session_id,
        cities=request.cities,
        start_date=request.start_date,
        end_date=request.end_date,
        days=days,
        weather_info=[],
        overall_suggestions="Mock trip plan for API contract validation.",
    )
