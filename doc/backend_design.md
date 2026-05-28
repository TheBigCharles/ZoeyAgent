# Backend Design

This document describes the backend service design for the travel planning assistant.

The backend is a self-hosted Python FastAPI app that exposes async endpoints, runs the LangGraph travel planner, manages memory dependencies, and returns structured Pydantic responses.

Frontend rendering is out of scope for this phase. The first implementation target is terminal-based backend testing with `curl`, HTTP clients, or pytest.

## Background

The system already has three design layers:

- `schemas_design.md`: Pydantic data contracts
- `agents_design.md`: LangGraph travel-planning workflow
- `memory_design.md`: working, semantic, and episodic memory design
- `tools_design.md`: Amap MCP integration, with photo enrichment deferred and route summaries allowed

The backend layer connects those designs into a running service.

The backend is responsible for:

- Accepting structured planning requests.
- Validating input with Pydantic.
- Running the async LangGraph planner.
- Resolving `session_id` and passing it as LangGraph `thread_id`.
- Managing Postgres-backed long-term memory.
- Managing `InMemorySaver` working-memory checkpoints.
- Returning validated `TripPlan` responses.
- Initializing and sharing external tool integrations such as the Amap MCP server.

## Design Decisions

### Async First

The backend should use async FastAPI route handlers and async graph invocation where possible.

`POST /api/trip/plan` should be async:

```python
@router.post("/plan", response_model=TripPlan)
async def create_trip_plan(request: TripPlanRequest) -> TripPlan:
    ...
```

The first version can run the graph within the request/response lifecycle. A background-job model can be added later if planning latency becomes too high.

### Session ID Is Resolved By Backend

`session_id` is optional on the first planning request.

Backend behavior:

- If `session_id` is missing, null, or blank, generate a new session ID.
- If `session_id` is present, trim and reuse it.
- Always use the resolved non-empty session ID as the LangGraph `thread_id`.
- Always return the resolved session ID in `TripPlan.session_id`.

Reason:

- `session_id` is the stable key for LangGraph `thread_id`.
- The frontend may not have a session before the first planning request.
- Once a session exists, the frontend owns continuity by sending that `session_id` on later requests.
- Terminal tests can either omit `session_id` to exercise generation or provide one to repeat a session.

Validation rule:

```text
TripPlanRequest.session_id is optional.
Graph execution requires a resolved non-empty session_id.
```

Generation rule:

```text
resolved_session_id = request.session_id or generate_session_id()
```

### Working Memory Uses LangGraph Checkpointer

Working memory is stored as LangGraph state with `InMemorySaver`.

The backend invokes the graph with:

```python
config = {
    "configurable": {
        "thread_id": resolved_session_id
    }
}
```

This lets later requests with the same `session_id` resume the same active planning state while the process is alive. If the first request omitted `session_id`, the frontend should read `TripPlan.session_id` from the response and send it on later requests.

### Long-Term Memory Uses PostgresStore

Semantic and episodic memory are stored in LangGraph `PostgresStore`.

The store uses:

- Postgres
- `pgvector`
- local vLLM OpenAI-compatible embeddings API
- `BAAI/bge-m3`
- 1024-dimensional vectors

The backend should interact with long-term memory through LangGraph Store APIs, not raw SQL.

## Service Structure

Recommended structure:

```text
app/
  main.py
  api/
    routes_health.py
    routes_trip.py
    routes_memory.py
  core/
    config.py
    dependencies.py
  schemas/
    trip.py
    memory.py
  agents/
    graph.py
    nodes/
    subgraphs/
  memory/
    store.py
    extraction.py
  tools/
    amap.py
    weather.py
```

For the first implementation, this can be simpler, but the boundaries should stay clear:

- `api`: HTTP routing
- `schemas`: Pydantic contracts
- `agents`: LangGraph construction and invocation
- `memory`: PostgresStore and extraction logic
- `tools`: external API clients
- `core`: config and dependency wiring

## Runtime Dependencies

The backend needs these runtime components:

```text
FastAPI app
LangGraph compiled graph
InMemorySaver checkpointer
PostgresStore
Embedding client pointing to vLLM /v1/embeddings
Amap/weather tool clients
LLM client for PlannerNode and extraction tasks
```

## Configuration

Expected environment variables:

```text
APP_ENV=local
POSTGRES_URL=postgresql://...

LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL=...

EMBEDDING_BASE_URL=http://localhost:8000/v1
EMBEDDING_API_KEY=dummy
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMS=1024

AMAP_API_KEY=...
```

The embedding endpoint should be OpenAI-compatible and served locally by vLLM.

## Application Lifecycle

On app startup:

1. Load config.
2. Initialize embedding client.
3. Initialize `PostgresStore` with embedding index config.
4. Initialize `InMemorySaver`.
5. Initialize shared Amap MCP tool/server integration.
6. Skip photo enrichment for the MVP; keep nullable image slots for future use.
7. Build and compile `TravelPlannerGraph`.
8. Register API routers.

On app shutdown:

1. Close database/store connections if needed.
2. Close HTTP clients if needed.

## Endpoints

### Health Check

```http
GET /health
```

Purpose:

- Verify the service is running.

Response:

```json
{
  "status": "ok"
}
```

### Trip Planning

```http
POST /api/trip/plan
```

Purpose:

- Run the full async `TravelPlannerGraph`.

Input:

```python
TripPlanRequest
```

Backend validation:

- `session_id` may be absent on the first request; the backend resolves it before graph execution.
- Date range must be valid.
- `cities` must be a non-empty list of valid strings.
- Preference indexes must match supported enum values.
- Budget, if provided, must be non-negative.

Flow:

```text
TripPlanRequest
  -> resolve session_id
  -> create initial TravelPlanState
  -> graph.ainvoke(state, config={"configurable": {"thread_id": session_id}})
  -> extract final TripPlan
  -> set TripPlan.session_id
  -> return TripPlan
```

Output:

```python
TripPlan
```

Response contract:

- `TripPlan.days[*]` is the primary rendering unit.
- Each day owns its `meals`, `map_points`, and `total_price`.
- Top-level `budget` and top-level `map_points` are not part of the response contract.
- Provider-returned text fields such as `city`, `name`, `address`, and `description` are returned as-is.
- `TripPlan.session_id` is always present and contains the resolved planning session ID.

Failure behavior:

- Invalid request -> FastAPI validation error.
- Missing `session_id` -> generate a new one.
- Graph fails unexpectedly -> 500 with structured error.
- Planner cannot produce valid plan after retries -> return fallback result if available, otherwise structured error.

### Recalculate Trip Plan

```http
POST /api/trip/recalculate
```

Status:

- Reserved for future implementation.

Signature:

```python
@router.post("/recalculate", response_model=TripPlan)
async def recalculate_trip_plan(request: TripRecalculateRequest) -> TripPlan:
    ...
```

For MVP:

- The route may return `501 Not Implemented`.
- The namespace and signature should be reserved.

Future use:

- Accept edited `TripPlan`.
- Recalculate per-day price totals.
- Recalculate route or map points.
- Apply local reorder/delete edits.
- Optionally trigger partial replanning.

### Memory Inspection: Semantic

```http
GET /api/memory/semantic
```

Purpose:

- Terminal/debug inspection of semantic memory for a user.

Query parameters:

```text
user_id: str
query: optional str
limit: int = 10
```

Behavior:

- If `query` is provided, call `PostgresStore.search((user_id, "semantic_memories"), query=query, limit=limit)`.
- If `query` is absent, list recent memories if supported by store implementation.

This endpoint is for backend testing and may be disabled in production.

### Memory Inspection: Episodic

```http
GET /api/memory/episodic
```

Purpose:

- Terminal/debug inspection of episodic memory for a user.

Query parameters:

```text
user_id: str
query: optional str
limit: int = 10
```

Behavior:

- If `query` is provided, call `PostgresStore.search((user_id, "episodic_memories"), query=query, limit=limit)`.
- If `query` is absent, list recent memories if supported by store implementation.

This endpoint is for backend testing and may be disabled in production.

## Async Graph Invocation

Route-level pseudocode:

```python
@router.post("/plan", response_model=TripPlan)
async def create_trip_plan(
    request: TripPlanRequest,
    graph: CompiledStateGraph = Depends(get_travel_graph),
) -> TripPlan:
    session_id = request.session_id or generate_session_id()

    resolved_request = request.model_copy(update={"session_id": session_id})
    initial_state = build_initial_state(resolved_request)
    config = {"configurable": {"thread_id": session_id}}

    result_state = await graph.ainvoke(initial_state, config=config)

    trip_plan = result_state.get("trip_plan")
    if trip_plan is None:
        raise HTTPException(status_code=500, detail="Trip plan was not generated")

    trip_plan.session_id = session_id
    return trip_plan
```

## Initial State

`build_initial_state(request)` should create:

```python
{
    "request": request,
    "working_messages": [
        {
            "role": "user",
            "content": request_to_text(request),
        }
    ],
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
```

## Error Handling

Use structured errors.

Recommended error shape:

```json
{
  "error": {
    "code": "GRAPH_EXECUTION_FAILED",
    "message": "Trip planning failed",
    "details": {}
  }
}
```

Common errors:

```text
INVALID_DATE_RANGE
GRAPH_EXECUTION_FAILED
TOOL_CALL_FAILED
PLAN_VALIDATION_FAILED
MEMORY_STORE_FAILED
```

For MVP, normal FastAPI exceptions are acceptable, but error codes should be introduced before frontend integration.

## Terminal Testing Plan

### Health

```bash
curl http://localhost:8000/health
```

### Plan Trip

Current request shape:

```json
{
  "user_id": "user_terminal_001",
  "cities": ["北京"],
  "start_date": "2026-06-10",
  "end_date": "2026-06-12",
  "preferences": {
    "transport_preference": 0,
    "accommodation_preference": [0],
    "attraction_preference": [0, 1]
  },
  "budget": 3000,
  "extra_requirements": "不要安排太赶"
}
```

Preference indexes:

```text
transport_preference:
  0 = public_transport
  1 = driving

accommodation_preference:
  0 = budget_hotel
  1 = mid_level_hotel
  2 = five_star_hotel

attraction_preference:
  0 = history_culture
  1 = nature
  2 = food
  3 = shopping
  4 = art
  5 = leisure
```

```bash
curl -X POST http://localhost:8000/api/trip/plan \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_terminal_001",
    "cities": ["北京"],
    "start_date": "2026-06-10",
    "end_date": "2026-06-12",
    "preferences": {
      "transport_preference": 0,
      "accommodation_preference": [0],
      "attraction_preference": [0, 1]
    },
    "budget": 3000,
    "extra_requirements": "不要安排太赶"
  }'
```

Expected:

- Response is valid `TripPlan`.
- Response includes `session_id`; if the request omitted it, this value was generated by the backend.
- `days` length matches date range.
- Each `days[*].meals` contains exactly one `breakfast`, one `lunch`, and one `dinner`.
- Each `days[*].total_price` is present and non-negative.
- Each `days[*].map_points` is populated when that day's locations are available.
- `Attraction.image_url` may be `null`; photo enrichment is deferred.
- `route_distance_km`, `route_duration_minutes`, and `transit_method` may be populated as lightweight route summaries.
- Full route instructions are not returned in MVP.
- `weather_info` is populated if weather API succeeds.
- No top-level `budget` or top-level `map_points` field is required; the frontend calculates trip total from `days[*].total_price`.
- Semantic/episodic memories may be written after validation.

### Search Semantic Memory

```bash
curl "http://localhost:8000/api/memory/semantic?user_id=user_terminal_001&query=用户喜欢什么旅行节奏&limit=5"
```

### Search Episodic Memory

```bash
curl "http://localhost:8000/api/memory/episodic?user_id=user_terminal_001&query=用户拒绝过什么酒店&limit=5"
```

## Deferred Items

Not part of the backend MVP:

- Frontend rendering
- Async background job queue
- WebSocket/SSE progress updates
- Authentication/authorization
- Production debug endpoint hardening
- Full `POST /api/trip/recalculate` implementation
- Deployment packaging

## Summary

The backend is an async FastAPI service that wraps the LangGraph travel planner.

The backend resolves `session_id`: it reuses a provided value or generates one when missing, then uses it as LangGraph `thread_id` for working-memory checkpoints and returns it in `TripPlan.session_id`. Long-term semantic and episodic memory use `PostgresStore` with `pgvector` and `BAAI/bge-m3` embeddings. The MVP exposes one real planning endpoint, one reserved recalculation endpoint, health checks, and optional memory-inspection endpoints for terminal testing.

