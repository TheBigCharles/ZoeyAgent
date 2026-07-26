"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes.health import router as health_router
from app.api.routes.map import router as map_router
from app.api.routes.memory import router as memory_router
from app.api.routes.trip import router as trip_router
from app.config import DependencyFactory, StructuredAppError, create_app_dependencies


def create_app(dependency_factory: DependencyFactory = create_app_dependencies) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.dependencies = None
        app.state.dependencies_startup_error = None
        try:
            dependencies = await dependency_factory()
            await dependencies.start()
            app.state.dependencies = dependencies
        except Exception as exc:
            app.state.dependencies_startup_error = exc
        try:
            yield
        finally:
            dependencies = getattr(app.state, "dependencies", None)
            if dependencies is not None:
                await dependencies.close()

    app = FastAPI(title="ZoeyAgent", lifespan=lifespan)

    @app.exception_handler(StructuredAppError)
    async def structured_app_error_handler(_, exc: StructuredAppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_response())

    app.include_router(health_router)
    app.include_router(trip_router)
    app.include_router(map_router)
    app.include_router(memory_router)
    return app


app = create_app()
