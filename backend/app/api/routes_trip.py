"""Trip planning routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/trip", tags=["trip"])


@router.post("/plan")
async def create_trip_plan() -> dict[str, str]:
    raise NotImplementedError
