# Example Workflow: Hangzhou Driving Trip

This example follows the current agents design exactly. It shows what each graph step does, which tools may be called, what output is expected, and when memory is saved.

## User Request

```text
目的地城市：杭州
开始日期：2026-07-05
结束日期：2026-07-08
交通偏好：driving
住宿偏好：budget_hotel
景点偏好：nature, shopping
额外要求：早上 11 点开始行程，晚上 10 点结束行程
```

Equivalent request shape:

```json
{
  "cities": ["杭州"],
  "start_date": "2026-07-05",
  "end_date": "2026-07-08",
  "preferences": {
    "transport_preference": 1,
    "accommodation_preference": [0],
    "attraction_preference": [1, 3]
  },
  "extra_requirements": "早上11点开始行程，晚上10点结束行程",
  "session_id": "frontend_generated_session_id"
}
```

Enum meaning:

```text
1 = driving
0 = budget_hotel
1 = nature
3 = shopping
```

Expected trip length: 4 days.

## Step 1: InitializeWorkingState

What it does:

- Creates the initial LangGraph state.
- Initializes working memory, tool observations, and trip draft.
- Stores the current request in working memory.

Tools called:

- None.

Expected output:

- Empty `TravelPlanState` with the user request attached.

Memory:

- Writes only to working memory.
- Does not write semantic or episodic memory.

## Step 2: LoadMemoryNode

What it does:

- Searches existing long-term memories for this user.
- Looks for relevant travel preferences and past decisions.
- Example: previous driving preference, hotel preference, nature/shopping interests.

Tools called:

- `PostgresStore.search(...)`
- Embedding search with pgvector.

Expected output:

- `semantic_memories`
- `episodic_memories`

Memory:

- Reads memory only.
- Does not save new memory.

## Step 3: NormalizeRequestNode

What it does:

- Validates dates and trip length.
- Converts frontend enum indexes into English enum values.
- Keeps provider-facing text such as city name as-is.
- Preserves long `extra_requirements`.

Expected normalized values:

```text
cities = ["杭州"]
days_count = 4
transport_preference = "driving"
accommodation_preferences = ["budget_hotel"]
attraction_preferences = ["nature", "shopping"]
extra_requirements = "早上11点开始行程，晚上10点结束行程"
```

Tools called:

- None.

Memory:

- Normalized request is stored in graph state.
- No long-term memory write.

## Step 4: AttractionSearchSubgraph

Goal:

- Find Hangzhou attraction candidates matching `nature` and `shopping`.
- Respect the daily time window: 11:00 to 22:00.

This is a local Plan-and-Solve subgraph.

### 4.1 AttractionTaskPlannerNode

What it does:

- Creates a local attraction-search plan.
- Converts preferences into provider search keywords.
- Calls LLM through `ContextAssembler(profile="attraction_task_planner")`.
- Uses `AttractionTaskPlannerPrompt`.

Possible keywords:

```text
自然风光
西湖
湿地公园
购物中心
湖滨银泰
杭州 商圈
```

Tools called:

- None at this planning step.

Expected output:

- Local attraction search plan.

### 4.2 AttractionReActStepExecutorNode

What it does:

- Executes each attraction-search step.
- Calls restricted Amap tools.
- Observes results and normalizes partial POI data.
- Calls LLM through `ContextAssembler(profile="attraction_step_executor")` when choosing the next tool/action.
- Uses `AttractionStepExecutorPrompt`.

Tools that may be called:

```text
amap_maps_text_search
amap_maps_search_detail
amap_maps_around_search
amap_maps_geocode
amap_maps_direction_walking_by_address
amap_maps_direction_driving_by_address
amap_maps_direction_transit_integrated_by_address
```

Direction tools are only used for summary signals:

- distance
- estimated time
- transport mode

They must not return full route instructions.

Not returned:

- bus/subway line details
- station counts
- turn-by-turn walking/driving instructions

### 4.3 AttractionStepEvaluatorNode

What it does:

- Checks whether attraction results are good enough.
- Validates result count, coordinates, address, preference match, and quality.
- If results are weak, asks executor to retry with different keywords or wider scope.
- If rule-based, it does not call LLM and does not use `ContextAssembler`.
- If LLM-based, it uses `ContextAssembler(profile="attraction_step_evaluator")`.

Expected candidate examples:

```text
西湖
西溪湿地
灵隐寺附近自然景区
湖滨银泰
武林商圈
杭州大厦
```

### 4.4 AttractionRankerNode

What it does:

- Deduplicates and ranks attraction candidates.
- Scores by preference match, location completeness, rating, estimated visit value, and itinerary diversity.

Expected output:

```text
AttractionSearchResult
- attractions
- search_keywords
- step_observations
- quality
```

Memory:

- Search attempts and candidates go to working memory / tool observations.
- No direct semantic or episodic memory write.

## Step 5: WeatherQueryNode

What it does:

- Queries weather for Hangzhou from 2026-07-05 to 2026-07-08.
- Deterministic node. It does not call LLM and does not use `ContextAssembler`.

Tools called:

```text
amap_maps_weather
```

Expected output:

```text
list[WeatherInfo]
```

Each weather record should include:

- `city = 杭州`
- `date`
- `day_weather`
- `night_weather`
- `day_temp`
- `night_temp`
- `wind_direction`
- `wind_power`

Memory:

- Weather result goes into graph state.
- No long-term memory write.

## Step 6: HotelSearchSubgraph

Goal:

- Find budget hotel candidates in Hangzhou.
- Because `transport_preference = driving`, parking is important.
- Hotel should be convenient for selected attractions, shopping areas, dinner areas, or transport-friendly areas.

This is a local Plan-and-Solve subgraph.

### 6.1 HotelTaskPlannerNode

What it does:

- Creates a local hotel-search plan.
- Chooses search anchors.
- Calls LLM through `ContextAssembler(profile="hotel_task_planner")`.
- Uses `HotelTaskPlannerPrompt`.

Possible anchors:

```text
西湖附近
湖滨银泰附近
武林商圈
西溪湿地附近
晚餐或购物区域附近
```

Tools called:

- None at this planning step.

Expected output:

- Local hotel search plan.

### 6.2 HotelReActStepExecutorNode

What it does:

- Searches hotel candidates around anchors.
- Checks nearby parking when driving is selected.
- Uses direction tools only for distance/time/mode summaries.
- Calls LLM through `ContextAssembler(profile="hotel_step_executor")` when choosing the next tool/action.
- Uses `HotelStepExecutorPrompt`.

Tools that may be called:

```text
amap_maps_text_search
amap_maps_around_search
amap_maps_geocode
amap_maps_direction_walking_by_address
amap_maps_direction_driving_by_address
amap_maps_direction_transit_integrated_by_address
```

Expected route summary signals:

- hotel-to-main-area distance
- estimated driving time
- transport mode = `driving`

Not returned:

- full driving route
- turn-by-turn instructions
- station or transfer details

### 6.3 HotelStepEvaluatorNode

What it does:

- Checks whether hotel candidates are valid.
- If invalid, asks executor to increase radius, switch anchor, or add a keyword.
- If rule-based, it does not call LLM and does not use `ContextAssembler`.
- If LLM-based, it uses `ContextAssembler(profile="hotel_step_evaluator")`.

Checks:

- enough candidates, about 10 if possible
- budget hotel match
- distance/time to main area
- rating and hotel level
- parking evidence or nearby parking lots
- enough location data

Important limitation:

- Amap POI can find hotel candidates.
- It cannot confirm real room availability.
- Output should be treated as `candidate_hotels`, not guaranteed available rooms.

### 6.4 HotelRankerNode

What it does:

- Ranks hotel candidates.
- Selects top 1 hotel for planning.
- Keeps other qualified candidates as alternatives.

Expected output:

```text
HotelSearchResult
- selected_hotel
- candidate_hotels
- ranking_reasons
- step_observations
- quality
```

Memory:

- `selected_hotel` and `candidate_hotels` go to working memory / tool observations.
- Does not directly write all candidates to long-term memory.
- Later, `SaveMemoryNode` may save useful stable preferences or confirmed decisions.

## Step 7: WorkingMemoryMaintenance

What it does:

- Checks whether working memory exceeds 50 messages.
- If not, nothing special happens.
- If yes, oldest overflow content is processed by `MemoryExtractionService`.

Tools called:

- No external travel tool.

Expected output:

- Updated working memory.
- Optional memory candidates if overflow happens.

Memory:

- If overflow happens:
  - stable preferences may become semantic memory
  - concrete trip decisions may become episodic memory
- In this example, overflow usually should not happen.

## Step 8: ContextAssemblyNode

What it does:

- Builds the planner context.
- Uses GSSC:
  - Gather
  - Select
  - Structure
  - Compress

Inputs:

- user request
- normalized request
- semantic memories
- episodic memories
- attraction search result
- weather info
- hotel search result
- tool observations
- extra requirements

Expected output:

```text
planner_context
```

Important context for PlannerNode:

- Hangzhou
- 4 days
- driving
- budget_hotel
- nature + shopping
- daily time window: 11:00 to 22:00
- use route summary only
- do not output full route instructions
- photo links are deferred

## Step 9: PlannerNode

What it does:

- Generates the complete `TripPlan`.
- Combines attractions, weather, hotel, meals, daily map points, and route summary signals.

Expected output:

```text
TripPlan
- cities = ["杭州"]
- start_date = 2026-07-05
- end_date = 2026-07-08
- days = 4 DayPlan objects
- weather_info
- overall_suggestions
```

Each `DayPlan` should include:

- `date`
- `city = 杭州`
- `description`
- `transportation = driving`
- `accommodation = budget_hotel`
- `hotel`
- `attractions`
- `meals`
  - `breakfast`
  - `lunch`
  - `dinner`
- `map_points`
- `total_price`
- `route_distance_km`
- `route_duration_minutes`
- `transit_method = driving`

Deferred / not returned:

- photo links
- full route instructions
- bus line details
- station counts
- transfer details
- turn-by-turn route instructions

`image_url` may be `null`.

## Step 10: ValidateTripPlanNode

What it does:

- Validates the generated `TripPlan`.
- If invalid, routes back to `PlannerNode` for repair.

Checks:

- response is a valid `TripPlan`
- exactly 4 days
- every day has one `breakfast`, one `lunch`, and one `dinner`
- every day has `total_price >= 0`
- every day has its own `map_points`
- no top-level `budget`
- no top-level `map_points`
- no full route instructions
- provider text such as `杭州`, addresses, and POI names stay as-is

Expected output:

- Validated `TripPlan`, or validation errors for repair.

Memory:

- No memory write here.

## Step 11: SaveMemoryNode

What it does:

- Runs only after validation succeeds.
- Extracts useful long-term memories from the completed graph state and final plan.

Possible semantic memory:

```text
User prefers driving.
User prefers budget_hotel.
User likes nature and shopping trips.
User prefers starting itinerary around 11:00.
User accepts ending itinerary around 22:00.
When driving, user cares about parking convenience.
```

Possible episodic memory:

```text
User planned a Hangzhou trip from 2026-07-05 to 2026-07-08.
This trip used a nature + shopping theme.
This trip selected a specific top hotel.
This trip kept several hotel candidates as alternatives.
```

Not saved:

- Full temporary POI search results.
- Every hotel candidate as long-term memory.
- Raw tool responses.

## Final Output Shape

The actual content depends on Amap tool results and PlannerNode generation. The structure should look like this:

```json
{
  "cities": ["杭州"],
  "start_date": "2026-07-05",
  "end_date": "2026-07-08",
  "days": [
    {
      "date": "2026-07-05",
      "day_index": 0,
      "city": "杭州",
      "description": "11点后开始，以自然风光和购物为主。",
      "transportation": "driving",
      "accommodation": "budget_hotel",
      "hotel": {},
      "attractions": [],
      "meals": [
        {"type": "breakfast"},
        {"type": "lunch"},
        {"type": "dinner"}
      ],
      "map_points": [],
      "total_price": 0,
      "route_distance_km": 0,
      "route_duration_minutes": 0,
      "transit_method": "driving"
    }
  ],
  "weather_info": [],
  "overall_suggestions": "...",
  "generated_at": "..."
}
```
