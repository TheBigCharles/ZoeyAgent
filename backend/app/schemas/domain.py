"""Core travel domain models shared by API, graph, tools, and planner output."""

from __future__ import annotations

from datetime import date as Date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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

