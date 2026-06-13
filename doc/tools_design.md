# Tools Design

This document describes the external tool integration design for the travel planning assistant.

The agents workflow depends on external services for location search and weather. These services should be wrapped behind clear tool/service boundaries so graph nodes do not need to know provider-specific API details.

## Background

The travel planner needs external data:

- Attractions and hotels from Amap POI search
- Weather from Amap weather tools
- Deferred attraction images from Unsplash or another image provider

External providers return inconsistent data shapes. For example, Amap may return coordinates as a string like `"116.397128,39.916527"`, while other providers may use `lng`, `lon`, `longitude`, or nested coordinate fields.

The tool layer is responsible for hiding those provider differences and returning normalized data that can be converted into the Pydantic schemas defined in `schemas_design.md`.

## Design Direction

Use MCP for Amap tools.

Defer direct service wrappers for Unsplash image enrichment.

Reasoning:

- Amap tools are interactive search/query tools used by graph subgraphs.
- Amap provides several related capabilities, so one shared MCP server is useful.
- Unsplash image lookup is deferred for the MVP. Schema slots can remain nullable for future enrichment.

## Amap MCP Integration

Use a shared Amap MCP server instance.

The backend acts as the MCP client. The Amap MCP server runs through stdio for the MVP and is owned by one shared `AmapMCPService` instance. The service may open the stdio session lazily on the first real tool call, but all Amap calls should still go through the same service boundary.

Conceptual setup:

```python
mcp_tool = MCPTool(
    name="amap_mcp",
    command="amap-mcp-server",
    args=[],
    env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
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
[TOOL_CALL:maps_text_search:keywords=景点,city=北京]
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

MVP required MCP tools:

- `maps_text_search`
- `maps_search_detail`
- `maps_geo`
- `maps_weather`
- `maps_direction_walking_by_address`
- `maps_direction_driving_by_address`
- `maps_direction_transit_integrated_by_address`

Future optional MCP tools:

- `maps_around_search`
- `maps_regeocode`

MVP usage:

- Attraction and hotel search use `maps_text_search`.
- POI coordinate enrichment uses `maps_search_detail` first and `maps_geo` as a fallback when text-search results do not include usable coordinates.
- Weather uses `maps_weather`.
- Search detail, around search, geocode, and regeocode are available to specialist subgraphs for step-level search refinement, radius expansion, parking checks, approximate coordinate-distance checks, and richer POI normalization.
- Direction tools may be used for lightweight route summary signals such as distance, estimated time, and transport mode. Full route instructions are deferred for the MVP.

### Attraction Search

Consumer:

- `AttractionSearchSubgraph`

Tool:

```text
maps_text_search
maps_search_detail
maps_around_search
maps_geo
maps_direction_walking_by_address
maps_direction_driving_by_address
maps_direction_transit_integrated_by_address
```

Inputs:

- `keywords`
- `city`

Output:

- raw MCP result text or structured content, depending on server response

Normalization target:

```python
AttractionSearchResult
```

The subgraph should never pass raw provider responses directly to `PlannerNode`. It should normalize, deduplicate, rank, and return Pydantic-compatible attraction candidates.

The attraction subgraph is a local Plan-and-Solve workflow. Its per-step ReAct executor may call restricted Amap tools, then a step evaluator decides whether the results are good enough or whether the subgraph should retry with alternate keywords, nearby anchors, or expanded search scope.

Optional refinements:

- `maps_search_detail` should enrich selected POIs when text search returns a POI ID but no coordinates.
- `maps_around_search` can find nearby attractions or restaurants once a location is known.
- `maps_geo` should convert city + address/name to coordinates when POI detail is unavailable or still lacks usable coordinates.
- Direction tools can estimate lightweight distance/time/mode between candidate attractions or from hotel anchors, but should not return step-by-step route instructions.

### Weather Query

Consumer:

- `WeatherQueryNode`

Tool:

```text
maps_weather
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
maps_text_search
maps_around_search
maps_geo
maps_direction_walking_by_address
maps_direction_driving_by_address
maps_direction_transit_integrated_by_address
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
HotelSearchResult
```

The hotel subgraph should evaluate distance, price, rating, hotel level, transportation convenience, and parking suitability before returning final hotel candidates.

The hotel subgraph is a local Plan-and-Solve workflow. Its task planner chooses hotel search anchors such as attraction clusters, dinner areas, transit hubs, business districts, or parking-convenient areas. Its ReAct executor calls restricted Amap POI/geocode/direction tools, then a step evaluator validates candidate count, distance/time quality, price/rating fit, and parking checks for driving trips.

Important limitation:

- Amap POI tools can discover hotel candidates and nearby parking, but they do not guarantee room availability for a date range.
- Until a booking/availability provider is added, the output should be treated as `candidate_hotels`, not confirmed available rooms.

Optional refinements:

- `maps_around_search` can search near selected attraction clusters.
- `maps_around_search` can search for nearby parking lots when the trip uses driving.
- `maps_search_detail` and `maps_geo` should be used to make hotel candidates map-ready before route summaries are computed.
- Direction tools can estimate public transit suitability, walkability, and driving convenience as summary signals.
- Direction tool outputs should be reduced to distance, estimated duration, and transport mode. Do not expose detailed route steps such as bus line, station count, turn-by-turn walking, or driving instructions in the MVP response.

### Route Summary and Geocoding Tools

Route and geocoding tools are part of the Amap MCP server. The MVP may use them for route summary signals, but full route planning instructions are deferred.

OCR source table confirms the available Amap MCP route/geocoding tools:

```text
maps_direction_walking_by_address
maps_direction_driving_by_address
maps_direction_transit_integrated_by_address
maps_geo
maps_regeocode
```

Allowed MVP use:

- distance radius checks
- estimated travel duration
- transport mode comparison
- hotel-to-attraction travel-time checks
- transit-oriented hotel selection
- address normalization

Deferred:

- map polyline display
- detailed bus/subway line instructions
- station counts
- turn-by-turn walking or driving instructions

If summary route data is unavailable, the graph should keep route slots nullable and return `route_distance_km = None` and `route_duration_minutes = None`.

Route summary is not map data. It contains only distance, estimated duration, and transport mode. Frontend map rendering still depends on `MapPoint.location`, so POI coordinate enrichment must run before building `DayPlan.map_points`.

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

Real `maps_text_search` responses from `sugarforever/amap-mcp-server` may contain only `id`, `name`, `address`, and `typecode`. In that case:

1. Call `maps_search_detail(id)` and use its `location`, `city`, `type`, and `biz_ext` fields when available.
2. If detail has no usable `location`, call `maps_geo(address=<address or name>, city=<city>)`.
3. Write the resulting `Location` back into the normalized `Attraction` or `Hotel`.
4. Generate `MapPoint` only from normalized entities that have valid coordinates.

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

## Deferred Unsplash Image Service

Unsplash/photo enrichment is deferred for the MVP.

It should not be exposed as a planner tool or called during terminal-first backend testing.

Reason:

- The planner does not need to decide whether images are required.
- Keeping it outside the graph reduces LLM/tool complexity.
- `Attraction.image_url` can remain as a nullable future slot.

Future wrapper:

```python
class UnsplashService:
    async def search_photos(self, query: str, per_page: int = 10) -> list[dict]:
        ...

    async def get_photo_url(self, query: str) -> str | None:
        ...
```

Future usage:

```text
TripPlan generated
  -> for each attraction without image_url
  -> search image by "{attraction.name} {attraction.city or day.city}"
  -> set image_url if found
```

For terminal-first backend testing, image enrichment should be disabled/deferred.

## Graph Integration

The tools layer is consumed by graph nodes/subgraphs:

```text
AttractionSearchSubgraph
  -> local task planner
  -> per-step ReAct executor with restricted Amap POI/detail/around/geocode tools
  -> step evaluator and bounded retry/replan
  -> normalize raw POIs to AttractionSearchResult

WeatherQueryNode
  -> Amap weather
  -> normalize raw weather to WeatherInfo

HotelSearchSubgraph
  -> local task planner
  -> per-step ReAct executor with restricted Amap POI/around/geocode/direction-summary tools
  -> step evaluator and bounded retry/replan
  -> normalize raw POIs to HotelSearchResult

Deferred post-processing
  -> UnsplashService
  -> enrich Attraction.image_url later
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
- Photo enrichment deferred -> leave `image_url = None`.
- Repeated tool failure in a required step -> surface structured error or fallback plan.

Tool observations should be summarized before being written to working memory:

```text
"Amap POI search for '历史文化' in 北京 returned 18 results; 9 retained after filtering."
```

Do not store full raw provider responses in working memory unless needed for debugging.

## Configuration

Expected environment variables:

```text
AMAP_MAPS_API_KEY=...
UNSPLASH_ACCESS_KEY=...
ENABLE_IMAGE_ENRICHMENT=false
```

MCP command configuration:

```text
AMAP_MCP_COMMAND=amap-mcp-server
AMAP_MCP_ARGS=
```

The command can later be changed to another MCP launcher if needed.

## Terminal Testing

Before full graph testing, tools should be tested independently.

Examples:

```text
search attractions in Beijing with keyword "历史文化"
query Beijing weather
search economy hotels in Beijing
normalize a real Amap coordinate string
```

Then test through graph-level endpoint:

```http
POST /api/trip/plan
```

## Deferred Items

Not required for MVP:

- Calling Unsplash/photo enrichment in MVP.
- Exposing Unsplash as an LLM-callable tool.
- Route planning tools.
- Multi-provider image search.
- Production-grade rate limiting.
- Tool-result caching.
- Full MCP server lifecycle dashboard.

## Summary

Amap should be integrated through one shared MCP server instance and consumed by the relevant LangGraph nodes/subgraphs. The tool layer should normalize provider responses into Pydantic-compatible domain models before data reaches `PlannerNode`. Photo enrichment and full route instructions are deferred for the MVP, while lightweight route summary signals may be used for ranking and planning support.
