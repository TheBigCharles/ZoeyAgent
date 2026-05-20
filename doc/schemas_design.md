# Schemas Design

This document defines the data contracts for the travel planning assistant.

The schemas are designed for three places at once:

- FastAPI request and response models
- LangGraph node input/output contracts
- LLM structured output validation

The goal is to avoid passing loose dictionaries between the frontend, backend, tools, graph nodes, and LLM. Instead, the system should use Pydantic models that are explicit, validated, serializable, and friendly to both humans and language models.

## Background

The frontend collects travel planning input from the user:

- Destination cities
- Start and end dates
- Travel preferences as enum indexes
- Budget
- Transportation preference
- Accommodation preference
- Extra requirements

The backend receives this input as `TripPlanRequest`, runs the LangGraph agents workflow, and returns a validated `TripPlan`.

The result page needs structured data for:

- Trip overview
- Per-day price totals
- Per-day map points
- Daily itinerary
- Weather information
- Hotel recommendation
- Meal suggestions
- Editable attraction cards

Because the frontend needs to render maps and editable itinerary cards, the response must include structured fields such as coordinates, attraction order, daily prices, daily map points, daily groupings, and weather. Trip-level price totals are calculated by the frontend from `days[*].total_price`.

## Design Principles

- Use Pydantic `BaseModel` for all external API models and important internal graph contracts.
- Prefer explicit field names over provider-specific names such as `lng`, `lon`, or `longitude`.
- Normalize external API responses into internal schemas as early as possible.
- Use nested models for real domain concepts such as `Location`, `Attraction`, `Hotel`, and `DayPlan`.
- Use validators for messy provider values such as temperatures, ratings, prices, and coordinate strings.
- Keep request/response schemas frontend-friendly.
- Keep graph-internal schemas separate from public API schemas where useful.

## Model Layers

```text
API models:
  TripPlanRequest
  TripPlan
  TripRecalculateRequest

Domain models:
  Location
  Attraction
  Hotel
  Meal
  WeatherInfo
  DayPlan

Graph/internal models:
  NormalizedTripRequest
  ContextPacket
  ContextConfig
  SearchQuality
  AttractionSearchResult
  HotelSearchResult
  MemoryCandidate
  WorkingMemoryMaintenanceResult
  TravelPlanState
```

## API Models

### Preference Enums

Frontend preference inputs are integer indexes. Backend schemas should convert those indexes into English enum values for normalized internal use. The frontend is responsible for translating enum values into display labels.

```python
from enum import IntEnum

class TransportPreference(IntEnum):
    PUBLIC_TRANSPORT = 0
    DRIVING = 1

    @property
    def value_en(self) -> str:
        return {
            TransportPreference.PUBLIC_TRANSPORT: "public_transport",
            TransportPreference.DRIVING: "driving",
        }[self]

class AccommodationPreference(IntEnum):
    BUDGET_HOTEL = 0
    MID_LEVEL_HOTEL = 1
    FIVE_STAR_HOTEL = 2

    @property
    def value_en(self) -> str:
        return {
            AccommodationPreference.BUDGET_HOTEL: "budget_hotel",
            AccommodationPreference.MID_LEVEL_HOTEL: "mid_level_hotel",
            AccommodationPreference.FIVE_STAR_HOTEL: "five_star_hotel",
        }[self]

class AttractionPreference(IntEnum):
    HISTORY_CULTURE = 0
    NATURE = 1
    FOOD = 2
    SHOPPING = 3
    ART = 4
    LEISURE = 5

    @property
    def value_en(self) -> str:
        return {
            AttractionPreference.HISTORY_CULTURE: "history_culture",
            AttractionPreference.NATURE: "nature",
            AttractionPreference.FOOD: "food",
            AttractionPreference.SHOPPING: "shopping",
            AttractionPreference.ART: "art",
            AttractionPreference.LEISURE: "leisure",
        }[self]
```

### TripPreferencesInput

```python
class TripPreferencesInput(BaseModel):
    transport_preference: TransportPreference = Field(..., description="Single transport preference enum index")
    accommodation_preference: list[AccommodationPreference] = Field(default_factory=list, description="Accommodation preference enum indexes")
    attraction_preference: list[AttractionPreference] = Field(default_factory=list, description="Attraction preference enum indexes")
```

Design notes:

- `transport_preference` is single-select.
- `accommodation_preference` is multi-select.
- `attraction_preference` is multi-select.
- The frontend sends integer indexes.
- Backend and LLM-facing normalized models should use English enum values.
- Provider-returned text fields such as `city`, `name`, `address`, and `description` should be preserved as-is.

### TripPlanRequest

`TripPlanRequest` is the public input model for `POST /api/trip/plan`.

It represents the frontend form.

```python
from datetime import date
from pydantic import BaseModel, Field, field_validator

class TripPlanRequest(BaseModel):
    user_id: str = Field(default="default_user", description="User identifier")
    cities: list[str] = Field(..., min_length=1, description="Destination cities")
    start_date: date = Field(..., description="Trip start date")
    end_date: date = Field(..., description="Trip end date")
    preferences: TripPreferencesInput = Field(..., description="Indexed frontend preference selections")
    budget: int | None = Field(default=None, ge=0, description="Total budget")
    extra_requirements: str = Field(default="", description="Free-form user requirements; may be long")
    session_id: str = Field(..., description="Client-generated planning session ID")

    @field_validator("cities")
    @classmethod
    def validate_cities(cls, value: list[str]) -> list[str]:
        cleaned = [city.strip() for city in value if city and city.strip()]
        if not cleaned:
            raise ValueError("cities must contain at least one valid city string")
        return cleaned
```

Design notes:

- `start_date` and `end_date` should be real `date` values, not free-form strings.
- `cities` is a non-empty list of valid city strings.
- `preferences` is a structured object containing enum indexes from the frontend.
- `transport_preference = 0` means `public_transport`, covering bus, train, subway, and taxi.
- Preference enum indexes are converted into English enum values during normalization. Frontend display translation is not a backend concern.
- `session_id` is required. The client/frontend generates it, and the backend uses it as the LangGraph `thread_id`.
- `extra_requirements` may be a very long string. It should be included in context assembly with token budgeting, not blindly expanded in every local subgraph prompt.

### TripPlan

`TripPlan` is the public response model for `POST /api/trip/plan`.

It must contain everything the frontend needs to render the result page.

```python
class TripPlan(BaseModel):
    cities: list[str] = Field(..., description="Destination cities")
    start_date: date = Field(..., description="Trip start date")
    end_date: date = Field(..., description="Trip end date")
    days: list[DayPlan] = Field(default_factory=list, description="Daily itinerary")
    weather_info: list[WeatherInfo] = Field(default_factory=list, description="Weather by date")
    overall_suggestions: str = Field(..., description="Overall travel suggestions")
    generated_at: str | None = Field(default=None, description="Generation timestamp")
```

Design notes:

- `TripPlan` is day-centric. It does not include top-level `budget` or top-level `map_points`.
- The frontend calculates total trip price by summing `days[*].total_price`.
- Each `DayPlan` owns its own `map_points` so the frontend can render per-day maps directly.
- Because `cities` can contain multiple destinations, `DayPlan`, `WeatherInfo`, and map/POI-like records should include `city` so the frontend and planner can distinguish records across cities.

### TripRecalculateRequest

Reserved for `POST /api/trip/recalculate`.

Concrete implementation is deferred, but the signature is reserved.

```python
class TripRecalculateRequest(BaseModel):
    user_id: str
    session_id: str | None = None
    trip_plan: TripPlan
    edit_reason: str | None = Field(default=None, description="Why the user edited the plan")
```

Future use:

- Recalculate per-day price totals after user edits.
- Recalculate map route after reorder/delete.
- Apply local itinerary edits.
- Optionally trigger partial replanning.

## Domain Models

### Location

```python
class Location(BaseModel):
    longitude: float = Field(..., ge=-180, le=180, description="Longitude")
    latitude: float = Field(..., ge=-90, le=90, description="Latitude")
```

External APIs should be normalized into this format, even if they return `lng`, `lon`, `longitude`, or `"116.397128,39.916527"`.

### Attraction

```python
class Attraction(BaseModel):
    name: str = Field(..., description="Attraction name")
    city: str | None = Field(default=None, description="City this attraction belongs to")
    address: str = Field(default="", description="Address")
    location: Location | None = Field(default=None, description="Coordinates")
    visit_duration: int = Field(default=90, gt=0, description="Suggested visit duration in minutes")
    description: str = Field(default="", description="Attraction description")
    category: str = Field(default="attraction", description="Attraction category")
    rating: float | None = Field(default=None, ge=0, le=5, description="Rating")
    image_url: str | None = Field(default=None, description="Deferred image URL slot")
    ticket_price: int = Field(default=0, ge=0, description="Ticket price")
    poi_id: str | None = Field(default=None, description="Provider POI ID")
    order_index: int | None = Field(default=None, ge=0, description="Order within the day")
    source: str | None = Field(default=None, description="Data source")
```

Design notes:

- `order_index` supports editable itinerary cards.
- `location` is optional at the model level because some provider results may be incomplete, but `ValidateTripPlanNode` should prefer complete map-ready attractions.
- `image_url` is intentionally nullable. Photo enrichment is deferred for the MVP.

### Hotel

```python
class Hotel(BaseModel):
    name: str = Field(..., description="Hotel name")
    city: str | None = Field(default=None, description="City this hotel belongs to")
    address: str = Field(default="", description="Hotel address")
    location: Location | None = Field(default=None, description="Hotel location")
    price_range: str = Field(default="", description="Price range")
    rating: float | None = Field(default=None, ge=0, le=5, description="Rating")
    distance: str = Field(default="", description="Distance description")
    type: str = Field(default="", description="Hotel type")
    estimated_cost: int = Field(default=0, ge=0, description="Estimated cost per night")
    poi_id: str | None = Field(default=None, description="Provider POI ID")
    distance_to_main_area_km: float | None = Field(default=None, ge=0, description="Distance to main itinerary area")
    estimated_travel_time_minutes: int | None = Field(default=None, ge=0, description="Estimated travel time to main itinerary area")
    transit_method: str | None = Field(default=None, description="Summary transport mode, such as walking/driving/transit")
    source: str | None = Field(default=None, description="Data source")
```

Design notes:

- Hotel route fields are summary signals for ranking and planning support.
- Do not store full route instructions such as bus lines, station counts, or turn-by-turn directions in the MVP.

### Meal

```python
from typing import Literal

MealType = Literal["breakfast", "lunch", "dinner"]

class Meal(BaseModel):
    type: MealType = Field(..., description="Meal type")
    name: str = Field(..., description="Restaurant or meal suggestion")
    city: str | None = Field(default=None, description="City this meal belongs to")
    address: str | None = Field(default=None, description="Address")
    location: Location | None = Field(default=None, description="Coordinates")
    description: str | None = Field(default=None, description="Description")
    estimated_cost: int = Field(default=0, ge=0, description="Estimated cost")
```

Design notes:

- Every `DayPlan.meals` list must contain exactly one `breakfast`, one `lunch`, and one `dinner`.
- Meal objects remain plain JSON dictionaries inside the `meals` list, so frontend extraction can key by `type`.

### WeatherInfo

```python
from pydantic import field_validator

class WeatherInfo(BaseModel):
    city: str = Field(..., description="City this weather record belongs to")
    date: date = Field(..., description="Weather date")
    day_weather: str = Field(..., description="Day weather")
    night_weather: str = Field(default="", description="Night weather")
    day_temp: int = Field(..., description="Day temperature in Celsius")
    night_temp: int = Field(..., description="Night temperature in Celsius")
    wind_direction: str = Field(default="", description="Wind direction")
    wind_power: str = Field(default="", description="Wind power")

    @field_validator("day_temp", "night_temp", mode="before")
    @classmethod
    def parse_temperature(cls, value):
        if isinstance(value, str):
            value = value.replace("°C", "").replace("℃", "").replace("°", "").strip()
            return int(value) if value.lstrip("-").isdigit() else 0
        return value
```

### MapPoint

```python
class MapPoint(BaseModel):
    name: str
    city: str | None = None
    location: Location
    day_index: int | None = None
    order_index: int | None = None
    point_type: str = Field(default="attraction", description="attraction/hotel/meal")
```

### DayPlan

```python
class DayPlan(BaseModel):
    date: date = Field(..., description="Date")
    day_index: int = Field(..., ge=0, description="Day index starting from 0")
    city: str = Field(..., description="City for this day")
    description: str = Field(..., description="Daily itinerary summary")
    transportation: str = Field(..., description="Transportation plan")
    accommodation: str = Field(..., description="Accommodation summary")
    hotel: Hotel | None = Field(default=None, description="Hotel for this day")
    attractions: list[Attraction] = Field(default_factory=list, description="Attractions")
    meals: list[Meal] = Field(default_factory=list, description="Meals")
    map_points: list[MapPoint] = Field(default_factory=list, description="Map points for this day")
    total_price: int = Field(default=0, ge=0, description="Total estimated price for this day")
    route_distance_km: float | None = Field(default=None, ge=0, description="Estimated route summary distance")
    route_duration_minutes: int | None = Field(default=None, ge=0, description="Estimated route summary duration")
    transit_method: str | None = Field(default=None, description="Summary transport mode for the day")
```

Design notes:

- `map_points` lives under each day, not at the top level.
- `total_price` is the only required price summary. The frontend calculates trip-level total by summing all days.
- `route_distance_km`, `route_duration_minutes`, and `transit_method` are lightweight route summary slots.
- They may be filled from Amap direction tools for ranking/planning support.
- Full route instructions are deferred and should not be returned in the MVP.

## Graph/Internal Models

### ContextPacket

Used by `ContextAssemblyNode` to represent candidate context before `PlannerNode`.

```python
from datetime import datetime

class ContextPacket(BaseModel):
    content: str
    timestamp: datetime
    token_count: int = Field(..., ge=0)
    relevance_score: float = Field(default=0.5, ge=0, le=1)
    recency_score: float = Field(default=0.5, ge=0, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source: str
    metadata: dict = Field(default_factory=dict)
```

### ContextConfig

Used by `ContextAssemblyNode` to control token budget, scoring, and compression.

```python
class ContextConfig(BaseModel):
    max_tokens: int = Field(default=6000, gt=0)
    reserve_ratio: float = Field(default=0.2, ge=0, le=1)
    min_relevance: float = Field(default=0.2, ge=0, le=1)
    enable_compression: bool = True
    relevance_weight: float = Field(default=0.55, ge=0, le=1)
    recency_weight: float = Field(default=0.20, ge=0, le=1)
    importance_weight: float = Field(default=0.15, ge=0, le=1)
    confidence_weight: float = Field(default=0.10, ge=0, le=1)
```

### ContextProfile

Used by reusable `ContextAssembler` instances to decide which information sources and output sections a specific LLM node may receive.

```python
class ContextProfile(BaseModel):
    profile_name: str
    max_tokens: int = Field(default=3000, gt=0)
    allowed_sources: list[str] = Field(default_factory=list)
    required_sections: list[str] = Field(default_factory=list)
    compression_policy: str = Field(default="trim_low_priority")
    output_schema_name: str | None = None
```

Example profile names:

```text
global_planner
attraction_task_planner
attraction_step_executor
attraction_step_evaluator
hotel_task_planner
hotel_step_executor
hotel_step_evaluator
repair_replan
```

### PromptTemplateSpec

Used by `PromptTemplateRegistry` to describe node-specific prompts.

```python
class PromptTemplateSpec(BaseModel):
    template_name: str
    role: str
    task: str
    input_fields: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    output_schema_name: str
    forbidden_outputs: list[str] = Field(default_factory=list)
```

### LLMNodeSpec

Used to document each node that talks to an LLM.

```python
class LLMNodeSpec(BaseModel):
    node_name: str
    context_profile: str
    prompt_template: str
    output_schema_name: str
    allowed_tools: list[str] = Field(default_factory=list)
    uses_context_assembler: bool = True
```

Design notes:

- Every LLM node must use `ContextAssembler`.
- Deterministic or rule-only nodes should not be modeled as `LLMNodeSpec`.
- `WeatherQueryNode` is deterministic and does not use `ContextAssembler`.

### SpecialistSearchConfig

Used to define a shared search-subgraph methodology with domain-specific configuration.

```python
class SpecialistSearchConfig(BaseModel):
    name: str
    planner_prompt: str
    executor_prompt: str
    evaluator_prompt: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    output_schema_name: str
    ranking_policy: str
    max_retries: int = Field(default=3, ge=0)
    memory_candidate_policy: str | None = None
```

Design notes:

- `AttractionSearchSubgraph` and `HotelSearchSubgraph` use the same methodology.
- They should not be forced into one universal subgraph because prompts, evaluator rules, ranking policies, tools, and output schemas are domain-specific.

### NormalizedTripRequest

`NormalizedTripRequest` is the cleaned version of `TripPlanRequest` used by graph nodes.
Preference fields contain English enum values such as `public_transport`, `budget_hotel`, and `history_culture`.
Provider text fields remain as returned by the provider.

```python
class NormalizedTripRequest(BaseModel):
    user_id: str
    cities: list[str]
    start_date: date
    end_date: date
    days_count: int = Field(..., gt=0)
    transport_preference: str
    accommodation_preferences: list[str] = Field(default_factory=list)
    attraction_preferences: list[str] = Field(default_factory=list)
    budget: int | None = Field(default=None, ge=0)
    extra_requirements: str = ""
    session_id: str
```

### SearchQuality

Used by search subgraphs to decide whether to retry.

```python
class SearchQuality(BaseModel):
    enough_results: bool
    result_count: int = Field(default=0, ge=0)
    reason: str = ""
    retry_suggested: bool = False
    next_keywords: list[str] = Field(default_factory=list)
```

### AttractionSearchResult

```python
class AttractionSearchResult(BaseModel):
    attractions: list[Attraction] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    step_observations: list[str] = Field(default_factory=list)
    quality: SearchQuality | None = None
```

### HotelSearchResult

```python
class HotelSearchResult(BaseModel):
    selected_hotel: Hotel | None = Field(default=None)
    candidate_hotels: list[Hotel] = Field(default_factory=list)
    search_areas: list[str] = Field(default_factory=list)
    ranking_reasons: list[str] = Field(default_factory=list)
    step_observations: list[str] = Field(default_factory=list)
    quality: SearchQuality | None = None
```

Design notes:

- `candidate_hotels` means qualified POI candidates, not confirmed available rooms.
- True date-range room availability requires a future booking/availability tool.
- `selected_hotel` is the top recommendation passed to the planner.
- Other qualified candidates should stay in working memory/tool observations and only become long-term memory if `MemoryExtractionService` classifies them as useful semantic or episodic memories.

### MemoryCandidate

Used by `SaveMemoryNode` before writing to long-term memory.

It is also used by `WorkingMemoryMaintenanceNode` when old working messages are about to be dropped.

```python
MemoryTarget = Literal["semantic", "episodic", "discard"]

class MemoryCandidate(BaseModel):
    target: MemoryTarget
    text: str
    reason: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    metadata: dict = Field(default_factory=dict)
```

### WorkingMemoryMaintenanceResult

Used when active working memory exceeds the configured message limit.

```python
class WorkingMemoryMaintenanceResult(BaseModel):
    retained_messages: list = Field(default_factory=list)
    extracted_candidates: list[MemoryCandidate] = Field(default_factory=list)
    dropped_count: int = Field(default=0, ge=0)
```

## TravelPlanState

LangGraph state is not necessarily a Pydantic model, but its fields should use these Pydantic models wherever possible.

```python
from typing import TypedDict

class TravelPlanState(TypedDict):
    request: TripPlanRequest
    normalized_request: NormalizedTripRequest

    working_messages: list
    trip_draft: dict
    tool_observations: list

    semantic_memories: list
    episodic_memories: list
    memory_candidates: list[MemoryCandidate]
    context_packets: list[ContextPacket]
    planner_context: str

    attraction_search_result: AttractionSearchResult
    attractions: list[Attraction]
    weather_info: list[WeatherInfo]
    hotel_search_result: HotelSearchResult
    hotels: list[Hotel]

    trip_plan: TripPlan | None
    validation_errors: list[str]
    retry_count: int
```

`attractions` and `hotels` are convenience flattened views. The richer `attraction_search_result` and `hotel_search_result` fields preserve subgraph plans, step observations, selected hotel, candidate hotels, quality checks, and ranking reasons.

## Endpoint Contracts

### Generate Trip Plan

```http
POST /api/trip/plan
```

Input:

```python
TripPlanRequest
```

Output:

```python
TripPlan
```

### Recalculate Trip Plan

Reserved for future edit/recalculate behavior.

```http
POST /api/trip/recalculate
```

Input:

```python
TripRecalculateRequest
```

Output:

```python
TripPlan
```

Concrete implementation is deferred.

## Validation Strategy

Validation happens at four boundaries:

1. API input: FastAPI validates `TripPlanRequest`.
2. Tool normalization: provider responses are converted into `Attraction`, `Hotel`, and `WeatherInfo`.
3. Planner output: `PlannerNode` output is parsed as `TripPlan`.
4. Final response: `ValidateTripPlanNode` checks structure before returning to frontend.

`ValidateTripPlanNode` should also enforce the day-centric contract:

- Each day contains exactly one `breakfast`, one `lunch`, and one `dinner`.
- Each day has `total_price >= 0`.
- Each day owns its own `map_points`.
- No top-level `budget` or top-level `map_points` field is required in the response.
- Provider-returned text fields such as `city`, `name`, `address`, and `description` are preserved as-is.

If planner validation fails, the graph routes back to `PlannerNode` for repair until retry limit is reached.

## Summary

The schema design follows the same bottom-up model as the reference Pydantic examples:

```text
Location
  -> Attraction / Hotel / Meal
  -> DayPlan
  -> TripPlan
```

It extends that baseline for the current LangGraph design by adding request models, graph-internal models, memory candidates, search result models, and a reserved recalculation contract.

The final goal is simple: every node should know what it receives, what it returns, and how that data will be validated before reaching the frontend.
