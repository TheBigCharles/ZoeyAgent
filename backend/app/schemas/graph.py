"""Graph-internal data contracts for LangGraph nodes and specialist subgraphs."""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime as DateTime
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from app.schemas.domain import Attraction, Hotel, WeatherInfo
from app.schemas.memory import MemoryCandidate
from app.schemas.trip import TripPlan, TripPlanRequest


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
