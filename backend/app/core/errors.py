"""Structured application error helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


GRAPH_EXECUTION_FAILED = "GRAPH_EXECUTION_FAILED"
TOOL_CALL_FAILED = "TOOL_CALL_FAILED"
PLAN_VALIDATION_FAILED = "PLAN_VALIDATION_FAILED"
CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


@dataclass(slots=True)
class StructuredAppError(Exception):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    status_code: int = 500

    def to_response(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


def exception_details(exc: Exception) -> dict[str, str]:
    return {"exception_type": type(exc).__name__}
