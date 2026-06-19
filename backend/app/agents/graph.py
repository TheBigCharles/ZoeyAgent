"""Travel planner LangGraph construction entrypoint."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.attraction_search import make_attraction_search_node
from app.agents.context import assemble_planner_context
from app.agents.hotel_search import make_hotel_search_node
from app.agents.nodes import (
    initialize_working_state,
    make_planner_node,
    make_weather_query_node,
    normalize_request,
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


def build_travel_planner_graph(amap_client=None, llm_service=None):
    """Build and compile the minimal async TravelPlannerGraph."""
    graph = StateGraph(TravelPlanState)
    graph.add_node("InitializeWorkingState", initialize_working_state)
    graph.add_node("NormalizeRequestNode", normalize_request)
    graph.add_node("AttractionSearchSubgraph", make_attraction_search_node(amap_client, llm_service))
    graph.add_node("HotelSearchSubgraph", make_hotel_search_node(amap_client, llm_service))
    graph.add_node("WeatherQueryNode", make_weather_query_node(amap_client))
    graph.add_node("ContextAssemblyNode", assemble_planner_context)
    graph.add_node("PlannerNode", make_planner_node(llm_service))
    graph.add_node("ValidateTripPlanNode", validate_trip_plan)

    graph.add_edge(START, "InitializeWorkingState")
    graph.add_edge("InitializeWorkingState", "NormalizeRequestNode")
    graph.add_edge("NormalizeRequestNode", "AttractionSearchSubgraph")
    graph.add_edge("AttractionSearchSubgraph", "HotelSearchSubgraph")
    graph.add_edge("HotelSearchSubgraph", "WeatherQueryNode")
    graph.add_edge("WeatherQueryNode", "ContextAssemblyNode")
    graph.add_edge("ContextAssemblyNode", "PlannerNode")
    graph.add_edge("PlannerNode", "ValidateTripPlanNode")
    graph.add_edge("ValidateTripPlanNode", END)

    return graph.compile()
