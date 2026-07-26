"""Trip planning routes."""

from uuid import uuid4

from fastapi import APIRouter, Depends

from app.config import (
    AppDependencies,
    GRAPH_EXECUTION_FAILED,
    PLAN_VALIDATION_FAILED,
    StructuredAppError,
    TRIP_RECALCULATION_NOT_IMPLEMENTED,
    exception_details,
    get_app_dependencies,
)
from app.agents.trip_planner_agent import build_initial_state
from app.schemas.trip import TripPlan, TripPlanRequest, TripRecalculateRequest

router = APIRouter(prefix="/api/trip", tags=["trip"])


@router.post("/plan", response_model=TripPlan)
async def create_trip_plan(
    request: TripPlanRequest,
    dependencies: AppDependencies = Depends(get_app_dependencies),
) -> TripPlan:
    session_id = request.session_id or str(uuid4())
    resolved_request = request.model_copy(update={"session_id": session_id})
    try:
        result_state = await dependencies.graph.ainvoke(
            build_initial_state(resolved_request),
            config={"configurable": {"thread_id": session_id}},
        )
    except StructuredAppError:
        raise
    except Exception as exc:
        raise StructuredAppError(
            code=GRAPH_EXECUTION_FAILED,
            message="Trip planning failed",
            details=exception_details(exc),
        ) from exc

    try:
        return TripPlan.model_validate(result_state["trip_plan"])
    except Exception as exc:
        raise StructuredAppError(
            code=PLAN_VALIDATION_FAILED,
            message="Trip plan validation failed",
            details=exception_details(exc),
        ) from exc


@router.post("/recalculate", response_model=TripPlan)
async def recalculate_trip_plan(_: TripRecalculateRequest) -> TripPlan:
    raise StructuredAppError(
        code=TRIP_RECALCULATION_NOT_IMPLEMENTED,
        message="Trip recalculation is reserved but not implemented",
        status_code=501,
    )
