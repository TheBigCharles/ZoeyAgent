"""Public trip-planning API request and response contracts."""

from __future__ import annotations

from datetime import date as Date
from enum import IntEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.domain import (
    Attraction,
    DayPlan,
    Hotel,
    Location,
    MapPoint,
    Meal,
    WeatherInfo,
)


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


__all__ = [
    "AccommodationPreference",
    "Attraction",
    "AttractionPreference",
    "DayPlan",
    "Hotel",
    "Location",
    "MapPoint",
    "Meal",
    "TransportPreference",
    "TripPlan",
    "TripPlanRequest",
    "TripPreferencesInput",
    "TripRecalculateRequest",
    "WeatherInfo",
]
