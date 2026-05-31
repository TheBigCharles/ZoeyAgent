"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes_health import router as health_router
from app.api.routes_trip import router as trip_router
from app.core.dependencies import DependencyFactory, create_app_dependencies
from app.core.errors import StructuredAppError


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
    return app


app = create_app()
