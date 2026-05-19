# Tools Design

This document describes the external tool integration design for the travel planning assistant.

The agents workflow depends on external services for location search, weather, and optional attraction images. These services should be wrapped behind clear tool/service boundaries so graph nodes do not need to know provider-specific API details.

## Background

The travel planner needs external data:

- Attractions and hotels from Amap POI search
- Weather from Amap weather tools
- Optional attraction images from Unsplash or another image provider

External providers return inconsistent data shapes. For example, Amap may return coordinates as a string like `"116.397128,39.916527"`, while other providers may use `lng`, `lon`, `longitude`, or nested coordinate fields.

The tool layer is responsible for hiding those provider differences and returning normalized data that can be converted into the Pydantic schemas defined in `schemas_design.md`.

## Design Direction

Use MCP for Amap tools.

Use a direct service wrapper for Unsplash image enrichment.

Reasoning:

- Amap tools are interactive search/query tools used by graph subgraphs.
- Amap provides several related capabilities, so one shared MCP server is useful.
- Unsplash image lookup is a simple enrichment step and does not require agent decision-making for the MVP.

## Amap MCP Integration

Use a shared Amap MCP server instance.

The backend acts as the MCP client. The Amap MCP server runs as a separate process and is started once by the backend service. Communication happens through the MCP transport supported by the launcher, commonly stdio for local process-based MCP servers. If the selected MCP runtime exposes HTTP instead, the same tool boundary still applies.

Conceptual setup:

```python
mcp_tool = MCPTool(
    name="amap_mcp",
    command="npx",
    args=["-y", "@sugarforever/amap-mcp-server"],
    env={"AMAP_API_KEY": settings.amap_api_key},
    auto_expand=True,
)
```

The exact runtime wrapper may differ from the example framework, but the design decision is the same:

```text
one shared Amap MCP process
auto-discovered tools
all Amap calls routed through that shared process
```

Conceptual call path:

```text
LangGraph node/subgraph
  -> shared MCP client/tool wrapper
  -> Amap MCP server process
  -> Amap external HTTP API
  -> MCP response
  -> normalized Pydantic model
```

The reference material shows HelloAgents parsing string markers such as:

```text
[TOOL_CALL:amap_maps_text_search:keywords=景点,city=北京]
```

This project should not depend on string tool-call markers inside prompts. In the LangGraph design, graph nodes/subgraphs call the tool wrapper directly or through structured tool-calling. The MCP server and Amap API usage are the same; only the agent-tool invocation style is different.

## Shared Tool Instance

The system should not start a separate Amap MCP server for each subgraph.

Use one shared instance because:

- It avoids multiple background MCP processes.
- It reduces CPU and memory overhead.
- It makes API rate limiting easier.
- It keeps tool availability consistent across subgraphs.

Consumers:

- `AttractionSearchSubgraph`
- `WeatherQueryNode`
- `HotelSearchSubgraph`
- future route/transport nodes

## Amap Tool Usage

Expected MCP tools:

- `amap_maps_text_search`
- `amap_maps_search_detail`
- `amap_maps_around_search`
- `amap_maps_weather`
- `amap_maps_direction_walking_by_address`
- `amap_maps_direction_driving_by_address`
- `amap_maps_direction_transit_integrated_by_address`
- `amap_maps_geocode`
- `amap_maps_regeocode`

MVP usage:

- Attraction and hotel search use `amap_maps_text_search`.
- Weather uses `amap_maps_weather`.
- Search detail, around search, directions, geocode, and regeocode are available for later route refinement, distance checks, and richer POI normalization.

### Attraction Search

Consumer:

- `AttractionSearchSubgraph`

Tool:

```text
amap_maps_text_search
```

Inputs:

- `keywords`
- `city`

Output:

- raw MCP result text or structured content, depending on server response

Normalization target:

```python
list[Attraction]
```

The subgraph should never pass raw provider responses directly to `PlannerNode`. It should normalize, deduplicate, rank, and return Pydantic-compatible attraction candidates.

Optional refinements:

- `amap_maps_search_detail` can enrich selected POIs.
- `amap_maps_around_search` can find nearby attractions or restaurants once a location is known.
- `amap_maps_geocode` can convert addresses to coordinates if POI search lacks usable coordinates.

### Weather Query

Consumer:

- `WeatherQueryNode`

Tool:

```text
amap_maps_weather
```

Inputs:

- `city`

Output:

- raw weather response

Normalization target:

```python
list[WeatherInfo]
```

`WeatherQueryNode` should normalize temperatures, dates, day/night weather, wind direction, and wind power into `WeatherInfo`.

### Hotel Search

Consumer:

- `HotelSearchSubgraph`

Tool:

```text
amap_maps_text_search
```

Inputs:

- `keywords`
- `city`

Example keyword strategies:

- `"经济型酒店"`
- `"豪华酒店"`
- `"{main_attraction_name} 附近 酒店"`
- `"{business_area} 酒店"`

Normalization target:

```python
list[Hotel]
```

The hotel subgraph should evaluate distance, price, rating, and suitability before returning final hotel candidates.

Optional refinements:

- `amap_maps_around_search` can search near selected attraction clusters.
- `amap_maps_direction_transit_integrated_by_address` can estimate public transit suitability.
- `amap_maps_direction_walking_by_address` can estimate walkability around a hotel area.

### Route and Geocoding Tools

Route planning and geocoding tools are part of the Amap MCP server but are deferred for the first backend MVP.

They should be considered when implementing:

- route distance and duration
- map polyline display
- hotel-to-attraction distance checks
- transit-oriented hotel selection
- address normalization

Until then, the graph can return `route_distance_km = None` and `route_duration_minutes = None` where route data is unavailable.

## Provider Response Normalization

Tool outputs should be normalized as early as possible.

### Coordinates

Amap may return coordinates as:

```text
"116.397128,39.916527"
```

Normalize to:

```python
Location(longitude=116.397128, latitude=39.916527)
```

### Ratings

Ratings may be returned as strings or missing values.

Normalize to:

```python
float | None
```

with valid range:

```text
0 <= rating <= 5
```

### Prices

Prices may be missing, free-form, or textual.

Normalize to:

```python
int
```

Use `0` when unknown or free.

### Images

Provider image URLs should map to:

```python
Attraction.image_url
```

If no image is available, keep `image_url = None`.

## Unsplash Image Service

Unsplash is an optional enrichment service.

It should not be exposed as a planner tool in the MVP.

Reason:

- The planner does not need to decide whether images are required.
- Image lookup can be a simple post-processing/enrichment step.
- Keeping it outside the graph reduces LLM/tool complexity.

Recommended wrapper:

```python
class UnsplashService:
    async def search_photos(self, query: str, per_page: int = 10) -> list[dict]:
        ...

    async def get_photo_url(self, query: str) -> str | None:
        ...
```

Usage:

```text
TripPlan generated
  -> for each attraction without image_url
  -> search image by "{attraction.name} {trip_plan.city}"
  -> set image_url if found
```

For terminal-first backend testing, image enrichment can be optional and disabled by config.

## Graph Integration

The tools layer is consumed by graph nodes/subgraphs:

```text
AttractionSearchSubgraph
  -> Amap text search
  -> normalize raw POIs to Attraction

WeatherQueryNode
  -> Amap weather
  -> normalize raw weather to WeatherInfo

HotelSearchSubgraph
  -> Amap text search
  -> normalize raw POIs to Hotel

Optional post-processing
  -> UnsplashService
  -> enrich Attraction.image_url
```

Specialist subgraphs should use restricted tool access:

- `AttractionSearchSubgraph` can use POI search tools.
- `WeatherQueryNode` can use weather tools.
- `HotelSearchSubgraph` can use POI/hotel search tools.

They should not receive unrelated tools.

## Error Handling

Tool failures should not crash the entire graph when a fallback is possible.

Recommended behavior:

- Amap POI failure -> return empty candidates and record tool observation.
- Weather failure -> continue with empty weather and note missing weather.
- Unsplash failure -> leave `image_url = None`.
- Repeated tool failure in a required step -> surface structured error or fallback plan.

Tool observations should be summarized before being written to working memory:

```text
"Amap POI search for '历史文化' in 北京 returned 18 results; 9 retained after filtering."
```

Do not store full raw provider responses in working memory unless needed for debugging.

## Configuration

Expected environment variables:

```text
AMAP_API_KEY=...
UNSPLASH_ACCESS_KEY=...
ENABLE_IMAGE_ENRICHMENT=false
```

MCP command configuration:

```text
AMAP_MCP_COMMAND=npx
AMAP_MCP_ARGS=-y @sugarforever/amap-mcp-server
```

The command can later be changed to another MCP launcher if needed.

## Terminal Testing

Before full graph testing, tools should be tested independently.

Examples:

```text
search attractions in Beijing with keyword "历史文化"
query Beijing weather
search economy hotels in Beijing
normalize a sample Amap coordinate string
```

Then test through graph-level endpoint:

```http
POST /api/trip/plan
```

## Deferred Items

Not required for MVP:

- Exposing Unsplash as an LLM-callable tool.
- Route planning tools.
- Multi-provider image search.
- Production-grade rate limiting.
- Tool-result caching.
- Full MCP server lifecycle dashboard.

## Summary

Amap should be integrated through one shared MCP server instance and consumed by the relevant LangGraph nodes/subgraphs. The tool layer should normalize provider responses into Pydantic-compatible domain models before data reaches `PlannerNode`. Unsplash image search should remain a simple optional enrichment service for MVP, not an agent tool.
