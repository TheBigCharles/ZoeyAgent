"""Trip planning routes."""

from uuid import uuid4

from fastapi import APIRouter

from app.agents.graph import build_initial_state, build_travel_planner_graph
from app.schemas.trip import TripPlan, TripPlanRequest

router = APIRouter(prefix="/api/trip", tags=["trip"])


@router.post("/plan", response_model=TripPlan)
async def create_trip_plan(request: TripPlanRequest) -> TripPlan:
    session_id = request.session_id or str(uuid4())
    resolved_request = request.model_copy(update={"session_id": session_id})
    graph = build_travel_planner_graph()
    result_state = await graph.ainvoke(
        build_initial_state(resolved_request),
        config={"configurable": {"thread_id": session_id}},
    )
    return TripPlan.model_validate(result_state["trip_plan"])
