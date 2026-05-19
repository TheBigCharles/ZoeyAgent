# Schemas Design

This document defines the data contracts for the travel planning assistant.

The schemas are designed for three places at once:

- FastAPI request and response models
- LangGraph node input/output contracts
- LLM structured output validation

The goal is to avoid passing loose dictionaries between the frontend, backend, tools, graph nodes, and LLM. Instead, the system should use Pydantic models that are explicit, validated, serializable, and friendly to both humans and language models.

## Background

The frontend collects travel planning input from the user:

- Destination city
- Start and end dates
- Travel preferences
- Budget
- Transportation type
- Accommodation type
- Extra requirements

The backend receives this input as `TripPlanRequest`, runs the LangGraph agents workflow, and returns a validated `TripPlan`.

The result page needs structured data for:

- Trip overview
- Budget breakdown
- Attraction map
- Daily itinerary
- Weather information
- Hotel recommendation
- Meal suggestions
- Editable attraction cards

Because the frontend needs to render maps and editable itinerary cards, the response must include structured fields such as coordinates, attraction order, prices, daily groupings, weather, and budget totals.

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
  Budget
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

### TripPlanRequest

`TripPlanRequest` is the public input model for `POST /api/trip/plan`.

It represents the frontend form.

```python
from datetime import date
from pydantic import BaseModel, Field

class TripPlanRequest(BaseModel):
    user_id: str = Field(default="default_user", description="User identifier")
    city: str = Field(..., description="Destination city")
    start_date: date = Field(..., description="Trip start date")
    end_date: date = Field(..., description="Trip end date")
    preferences: list[str] = Field(default_factory=list, description="Travel preferences")
    budget: int | None = Field(default=None, ge=0, description="Total budget")
    transportation: str = Field(default="public_transit", description="Preferred transportation")
    accommodation: str = Field(default="economy", description="Accommodation preference")
    extra_requirements: str | None = Field(default=None, description="Free-form user requirements")
    session_id: str = Field(..., description="Client-generated planning session ID")
```

Design notes:

- `start_date` and `end_date` should be real `date` values, not free-form strings.
- `preferences` is a list so the frontend can pass checkbox values directly.
- `session_id` is required. The client/frontend generates it, and the backend uses it as the LangGraph `thread_id`.

### TripPlan

`TripPlan` is the public response model for `POST /api/trip/plan`.

It must contain everything the frontend needs to render the result page.

```python
class TripPlan(BaseModel):
    city: str = Field(..., description="Destination city")
    start_date: date = Field(..., description="Trip start date")
    end_date: date = Field(..., description="Trip end date")
    days: list[DayPlan] = Field(default_factory=list, description="Daily itinerary")
    weather_info: list[WeatherInfo] = Field(default_factory=list, description="Weather by date")
    overall_suggestions: str = Field(..., description="Overall travel suggestions")
    budget: Budget = Field(default_factory=Budget, description="Budget breakdown")
    map_points: list[MapPoint] = Field(default_factory=list, description="Points used by the map")
    generated_at: str | None = Field(default=None, description="Generation timestamp")
```

Design notes:

- `map_points` can be derived from `days[*].attractions`, but including it makes the frontend simpler.
- `budget` should default to an empty budget object instead of `None`, so the frontend can render consistently.

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

- Recalculate budget after user edits.
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
    address: str = Field(default="", description="Address")
    location: Location | None = Field(default=None, description="Coordinates")
    visit_duration: int = Field(default=90, gt=0, description="Suggested visit duration in minutes")
    description: str = Field(default="", description="Attraction description")
    category: str = Field(default="attraction", description="Attraction category")
    rating: float | None = Field(default=None, ge=0, le=5, description="Rating")
    image_url: str | None = Field(default=None, description="Image URL")
    ticket_price: int = Field(default=0, ge=0, description="Ticket price")
    poi_id: str | None = Field(default=None, description="Provider POI ID")
    order_index: int | None = Field(default=None, ge=0, description="Order within the day")
    source: str | None = Field(default=None, description="Data source")
```

Design notes:

- `order_index` supports editable itinerary cards.
- `location` is optional at the model level because some provider results may be incomplete, but `ValidateTripPlanNode` should prefer complete map-ready attractions.

### Hotel

```python
class Hotel(BaseModel):
    name: str = Field(..., description="Hotel name")
    address: str = Field(default="", description="Hotel address")
    location: Location | None = Field(default=None, description="Hotel location")
    price_range: str = Field(default="", description="Price range")
    rating: float | None = Field(default=None, ge=0, le=5, description="Rating")
    distance: str = Field(default="", description="Distance description")
    type: str = Field(default="", description="Hotel type")
    estimated_cost: int = Field(default=0, ge=0, description="Estimated cost per night")
    poi_id: str | None = Field(default=None, description="Provider POI ID")
    distance_to_main_area_km: float | None = Field(default=None, ge=0, description="Distance to main itinerary area")
    source: str | None = Field(default=None, description="Data source")
```

### Meal

```python
from typing import Literal

MealType = Literal["breakfast", "lunch", "dinner", "snack"]

class Meal(BaseModel):
    type: MealType = Field(..., description="Meal type")
    name: str = Field(..., description="Restaurant or meal suggestion")
    address: str | None = Field(default=None, description="Address")
    location: Location | None = Field(default=None, description="Coordinates")
    description: str | None = Field(default=None, description="Description")
    estimated_cost: int = Field(default=0, ge=0, description="Estimated cost")
```

### WeatherInfo

```python
from pydantic import field_validator

class WeatherInfo(BaseModel):
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

### Budget

```python
class Budget(BaseModel):
    total_attractions: int = Field(default=0, ge=0, description="Total attraction tickets")
    total_hotels: int = Field(default=0, ge=0, description="Total hotel cost")
    total_meals: int = Field(default=0, ge=0, description="Total meal cost")
    total_transportation: int = Field(default=0, ge=0, description="Total transportation cost")
    total: int = Field(default=0, ge=0, description="Total estimated cost")
```

### DayPlan

```python
class DayPlan(BaseModel):
    date: date = Field(..., description="Date")
    day_index: int = Field(..., ge=0, description="Day index starting from 0")
    description: str = Field(..., description="Daily itinerary summary")
    transportation: str = Field(..., description="Transportation plan")
    accommodation: str = Field(..., description="Accommodation summary")
    hotel: Hotel | None = Field(default=None, description="Hotel for this day")
    attractions: list[Attraction] = Field(default_factory=list, description="Attractions")
    meals: list[Meal] = Field(default_factory=list, description="Meals")
    route_distance_km: float | None = Field(default=None, ge=0, description="Estimated route distance")
    route_duration_minutes: int | None = Field(default=None, ge=0, description="Estimated route duration")
```

### MapPoint

```python
class MapPoint(BaseModel):
    name: str
    location: Location
    day_index: int | None = None
    order_index: int | None = None
    point_type: str = Field(default="attraction", description="attraction/hotel/meal")
```

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

### NormalizedTripRequest

`NormalizedTripRequest` is the cleaned version of `TripPlanRequest` used by graph nodes.

```python
class NormalizedTripRequest(BaseModel):
    user_id: str
    city: str
    start_date: date
    end_date: date
    days_count: int = Field(..., gt=0)
    preferences: list[str] = Field(default_factory=list)
    budget: int | None = Field(default=None, ge=0)
    transportation: str
    accommodation: str
    extra_requirements: str | None = None
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
    quality: SearchQuality | None = None
```

### HotelSearchResult

```python
class HotelSearchResult(BaseModel):
    hotels: list[Hotel] = Field(default_factory=list)
    search_areas: list[str] = Field(default_factory=list)
    quality: SearchQuality | None = None
```

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

    attractions: list[Attraction]
    weather_info: list[WeatherInfo]
    hotels: list[Hotel]

    trip_plan: TripPlan | None
    validation_errors: list[str]
    retry_count: int
```

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
