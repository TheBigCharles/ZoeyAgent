"""Travel planning request, response, domain, and graph data contracts."""

from __future__ import annotations

from collections import Counter
from datetime import date as Date
from datetime import datetime as DateTime
from enum import IntEnum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator, model_validator


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


class TripPreferencesInput(BaseModel):
    transport_preference: TransportPreference = Field(..., description="Single transport preference enum index")
    accommodation_preference: list[AccommodationPreference] = Field(
        default_factory=list,
        description="Accommodation preference enum indexes",
    )
    attraction_preference: list[AttractionPreference] = Field(
        default_factory=list,
        description="Attraction preference enum indexes",
    )


class TripPlanRequest(BaseModel):
    user_id: str = Field(default="default_user", description="User identifier")
    cities: list[str] = Field(..., min_length=1, description="Destination cities")
    start_date: Date = Field(..., description="Trip start date")
    end_date: Date = Field(..., description="Trip end date")
    preferences: TripPreferencesInput = Field(..., description="Indexed frontend preference selections")
    budget: int | None = Field(default=None, ge=0, description="Total budget")
    extra_requirements: str = Field(default="", description="Free-form user requirements")
    session_id: str | None = Field(default=None, description="Existing planning session ID, if available")

    @field_validator("cities")
    @classmethod
    def validate_cities(cls, value: list[str]) -> list[str]:
        cleaned = [city.strip() for city in value if city and city.strip()]
        if not cleaned:
            raise ValueError("cities must contain at least one valid city string")
        return cleaned

    @field_validator("session_id", mode="before")
    @classmethod
    def normalize_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_date_range(self) -> TripPlanRequest:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class Location(BaseModel):
    longitude: float = Field(..., ge=-180, le=180, description="Longitude")
    latitude: float = Field(..., ge=-90, le=90, description="Latitude")


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
    distance_to_main_area_km: float | None = Field(default=None, ge=0)
    estimated_travel_time_minutes: int | None = Field(default=None, ge=0)
    transit_method: str | None = Field(default=None, description="Summary transport mode")
    source: str | None = Field(default=None, description="Data source")


MealType = Literal["breakfast", "lunch", "dinner"]


class Meal(BaseModel):
    type: MealType = Field(..., description="Meal type")
    name: str = Field(..., description="Restaurant or meal suggestion")
    city: str | None = Field(default=None, description="City this meal belongs to")
    address: str | None = Field(default=None, description="Address")
    location: Location | None = Field(default=None, description="Coordinates")
    description: str | None = Field(default=None, description="Description")
    estimated_cost: int = Field(default=0, ge=0, description="Estimated cost")


class WeatherInfo(BaseModel):
    city: str = Field(..., description="City this weather record belongs to")
    date: Date = Field(..., description="Weather date")
    day_weather: str = Field(..., description="Day weather")
    night_weather: str = Field(default="", description="Night weather")
    day_temp: int = Field(..., description="Day temperature in Celsius")
    night_temp: int = Field(..., description="Night temperature in Celsius")
    wind_direction: str = Field(default="", description="Wind direction")
    wind_power: str = Field(default="", description="Wind power")

    @field_validator("day_temp", "night_temp", mode="before")
    @classmethod
    def parse_temperature(cls, value: Any) -> int:
        if isinstance(value, str):
            cleaned = value.replace("°C", "").replace("℃", "").replace("°", "").strip()
            return int(cleaned) if cleaned.lstrip("-").isdigit() else 0
        return value


class MapPoint(BaseModel):
    name: str
    city: str | None = None
    location: Location
    day_index: int | None = None
    order_index: int | None = None
    point_type: str = Field(default="attraction", description="attraction/hotel/meal")


class DayPlan(BaseModel):
    date: Date = Field(..., description="Date")
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

    @field_validator("meals")
    @classmethod
    def validate_meals(cls, value: list[Meal]) -> list[Meal]:
        meal_counts = Counter(meal.type for meal in value)
        expected = {"breakfast": 1, "lunch": 1, "dinner": 1}
        if dict(meal_counts) != expected:
            raise ValueError("meals must contain exactly one breakfast, one lunch, and one dinner")
        return value


class TripPlan(BaseModel):
    session_id: str = Field(..., min_length=1, description="Resolved planning session ID")
    cities: list[str] = Field(..., min_length=1, description="Destination cities")
    start_date: Date = Field(..., description="Trip start date")
    end_date: Date = Field(..., description="Trip end date")
    days: list[DayPlan] = Field(default_factory=list, description="Daily itinerary")
    weather_info: list[WeatherInfo] = Field(default_factory=list, description="Weather by date")
    overall_suggestions: str = Field(..., description="Overall travel suggestions")
    generated_at: str | None = Field(default=None, description="Generation timestamp")

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("session_id is required")
        return cleaned

    @model_validator(mode="after")
    def validate_trip_dates_and_days(self) -> TripPlan:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        expected_days = (self.end_date - self.start_date).days + 1
        if len(self.days) != expected_days:
            raise ValueError("days length must match the inclusive date range")
        return self


class TripRecalculateRequest(BaseModel):
    user_id: str
    session_id: str | None = None
    trip_plan: TripPlan
    edit_reason: str | None = Field(default=None, description="Why the user edited the plan")


class ContextPacket(BaseModel):
    content: str
    timestamp: DateTime
    token_count: int = Field(..., ge=0)
    relevance_score: float = Field(default=0.5, ge=0, le=1)
    recency_score: float = Field(default=0.5, ge=0, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextConfig(BaseModel):
    max_tokens: int = Field(default=6000, gt=0)
    reserve_ratio: float = Field(default=0.2, ge=0, le=1)
    min_relevance: float = Field(default=0.2, ge=0, le=1)
    enable_compression: bool = True
    relevance_weight: float = Field(default=0.55, ge=0, le=1)
    recency_weight: float = Field(default=0.20, ge=0, le=1)
    importance_weight: float = Field(default=0.15, ge=0, le=1)
    confidence_weight: float = Field(default=0.10, ge=0, le=1)


class ContextProfile(BaseModel):
    profile_name: str
    max_tokens: int = Field(default=3000, gt=0)
    allowed_sources: list[str] = Field(default_factory=list)
    required_sections: list[str] = Field(default_factory=list)
    compression_policy: str = Field(default="trim_low_priority")
    output_schema_name: str | None = None


class PromptTemplateSpec(BaseModel):
    template_name: str
    role: str
    task: str
    input_fields: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    output_schema_name: str
    forbidden_outputs: list[str] = Field(default_factory=list)


class LLMNodeSpec(BaseModel):
    node_name: str
    context_profile: str
    prompt_template: str
    output_schema_name: str
    allowed_tools: list[str] = Field(default_factory=list)
    uses_context_assembler: bool = True


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


class NormalizedTripRequest(BaseModel):
    user_id: str
    cities: list[str]
    start_date: Date
    end_date: Date
    days_count: int = Field(..., gt=0)
    transport_preference: str
    accommodation_preferences: list[str] = Field(default_factory=list)
    attraction_preferences: list[str] = Field(default_factory=list)
    budget: int | None = Field(default=None, ge=0)
    extra_requirements: str = ""
    session_id: str


class SearchQuality(BaseModel):
    enough_results: bool
    result_count: int = Field(default=0, ge=0)
    reason: str = ""
    retry_suggested: bool = False
    next_keywords: list[str] = Field(default_factory=list)


class AttractionSearchResult(BaseModel):
    attractions: list[Attraction] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    step_observations: list[str] = Field(default_factory=list)
    quality: SearchQuality | None = None


class HotelSearchResult(BaseModel):
    selected_hotel: Hotel | None = Field(default=None)
    candidate_hotels: list[Hotel] = Field(default_factory=list)
    search_areas: list[str] = Field(default_factory=list)
    ranking_reasons: list[str] = Field(default_factory=list)
    step_observations: list[str] = Field(default_factory=list)
    quality: SearchQuality | None = None


MemoryTarget = Literal["semantic", "episodic", "discard"]


class MemoryCandidate(BaseModel):
    target: MemoryTarget
    text: str
    reason: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkingMemoryMaintenanceResult(BaseModel):
    retained_messages: list[Any] = Field(default_factory=list)
    extracted_candidates: list[MemoryCandidate] = Field(default_factory=list)
    dropped_count: int = Field(default=0, ge=0)


class TravelPlanState(TypedDict, total=False):
    request: TripPlanRequest
    normalized_request: NormalizedTripRequest
    working_messages: list[Any]
    trip_draft: dict[str, Any]
    tool_observations: list[Any]
    semantic_memories: list[Any]
    episodic_memories: list[Any]
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
