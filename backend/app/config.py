"""Application configuration, dependency wiring, and structured errors."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from fastapi import Request
from langgraph.checkpoint.memory import InMemorySaver

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    postgres_url: str | None = Field(default=None, alias="POSTGRES_URL")

    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4.1-mini", alias="LLM_MODEL")

    embedding_base_url: str = Field(default="http://localhost:8000/v1", alias="EMBEDDING_BASE_URL")
    embedding_api_key: str = Field(default="dummy", alias="EMBEDDING_API_KEY")
    embedding_model: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL")
    embedding_dims: int = Field(default=1024, alias="EMBEDDING_DIMS")

    amap_api_key: str | None = Field(default=None, alias="AMAP_API_KEY")
    amap_mcp_command: str = Field(default="npx", alias="AMAP_MCP_COMMAND")
    amap_mcp_args: str = Field(default="-y @sugarforever/amap-mcp-server", alias="AMAP_MCP_ARGS")

    enable_image_enrichment: bool = Field(default=False, alias="ENABLE_IMAGE_ENRICHMENT")
    unsplash_access_key: str | None = Field(default=None, alias="UNSPLASH_ACCESS_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()


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


@dataclass(slots=True)
class AppDependencies:
    graph: Any
    settings: Settings | None = None
    checkpointer: Any | None = None
    store: Any | None = None
    amap_client: Any | None = None
    llm_client: Any | None = None

    async def start(self) -> None:
        if self.amap_client is not None:
            await self.amap_client.start()

    async def close(self) -> None:
        if self.amap_client is not None:
            await self.amap_client.close()


DependencyFactory = Callable[[], Awaitable[AppDependencies]]


async def create_app_dependencies() -> AppDependencies:
    from app.agents.trip_planner_agent import build_travel_planner_graph
    from app.services.amap_service import AmapMCPService
    from app.services.llm_service import LLMService

    settings = get_settings()
    return AppDependencies(
        settings=settings,
        graph=build_travel_planner_graph(),
        checkpointer=InMemorySaver(),
        store=None,
        amap_client=AmapMCPService(settings=settings),
        llm_client=LLMService(settings=settings),
    )


def get_app_dependencies(request: Request) -> AppDependencies:
    startup_error = getattr(request.app.state, "dependencies_startup_error", None)
    if startup_error is not None:
        raise StructuredAppError(
            code=CONFIGURATION_ERROR,
            message="Application dependencies are not available",
            details=exception_details(startup_error),
        )

    dependencies = getattr(request.app.state, "dependencies", None)
    if dependencies is None:
        raise StructuredAppError(
            code=CONFIGURATION_ERROR,
            message="Application dependencies are not available",
            details={"exception_type": "RuntimeError"},
        )
    return dependencies
