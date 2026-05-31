"""Application dependency wiring and lifecycle helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.graph import build_travel_planner_graph
from app.agents.llm import LLMService
from app.core.config import Settings, get_settings
from app.core.errors import CONFIGURATION_ERROR, StructuredAppError, exception_details
from app.tools.amap import AmapMCPService


@dataclass(slots=True)
class AppDependencies:
    graph: Any
    settings: Settings | None = None
    checkpointer: Any | None = None
    store: Any | None = None
    amap_client: AmapMCPService | None = None
    llm_client: LLMService | None = None

    async def start(self) -> None:
        if self.amap_client is not None:
            await self.amap_client.start()

    async def close(self) -> None:
        if self.amap_client is not None:
            await self.amap_client.close()


DependencyFactory = Callable[[], Awaitable[AppDependencies]]


async def create_app_dependencies() -> AppDependencies:
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
