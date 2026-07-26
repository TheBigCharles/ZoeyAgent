"""Travel planner agent composition entrypoint.

This module is the public facade for the trip-planning agent. Keep graph,
context assembly, and node implementations split across focused modules, and
re-export the composed graph API here.
"""

from app.agents.context import (
    ContextAssembler,
    MainPlannerContextAssemblyNode,
    SpecialistContextBuilder,
    assemble_planner_context,
)
from app.agents.graph import build_initial_state, build_travel_planner_graph
from app.agents.nodes import (
    initialize_working_state,
    make_load_memory_node,
    make_planner_node,
    make_save_memory_node,
    normalize_request,
    planner_node,
    validate_trip_plan,
)
from app.agents.attraction_search import make_attraction_search_node
from app.agents.hotel_search import make_hotel_search_node

__all__ = [
    "ContextAssembler",
    "MainPlannerContextAssemblyNode",
    "SpecialistContextBuilder",
    "assemble_planner_context",
    "build_initial_state",
    "build_travel_planner_graph",
    "initialize_working_state",
    "make_attraction_search_node",
    "make_hotel_search_node",
    "make_load_memory_node",
    "make_planner_node",
    "make_save_memory_node",
    "normalize_request",
    "planner_node",
    "validate_trip_plan",
]
