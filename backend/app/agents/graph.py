"""Travel planner LangGraph construction entrypoint."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    initialize_working_state,
    normalize_request,
    planner_node,
    validate_trip_plan,
)
from app.schemas.graph import TravelPlanState
from app.schemas.trip import TripPlanRequest


def build_initial_state(request: TripPlanRequest) -> TravelPlanState:
    return {
        "request": request,
        "working_messages": [],
        "trip_draft": {},
        "tool_observations": [],
        "memory_candidates": [],
        "semantic_memories": [],
        "episodic_memories": [],
        "context_packets": [],
        "planner_context": "",
        "attractions": [],
        "weather_info": [],
        "hotels": [],
        "trip_plan": None,
        "validation_errors": [],
        "retry_count": 0,
    }


def build_travel_planner_graph():
    """Build and compile the minimal async TravelPlannerGraph."""
    graph = StateGraph(TravelPlanState)
    graph.add_node("InitializeWorkingState", initialize_working_state)
    graph.add_node("NormalizeRequestNode", normalize_request)
    graph.add_node("PlannerNode", planner_node)
    graph.add_node("ValidateTripPlanNode", validate_trip_plan)

    graph.add_edge(START, "InitializeWorkingState")
    graph.add_edge("InitializeWorkingState", "NormalizeRequestNode")
    graph.add_edge("NormalizeRequestNode", "PlannerNode")
    graph.add_edge("PlannerNode", "ValidateTripPlanNode")
    graph.add_edge("ValidateTripPlanNode", END)

    return graph.compile()
