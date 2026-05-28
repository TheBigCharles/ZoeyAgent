"""Memory-related data contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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
