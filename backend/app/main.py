"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.routes_health import router as health_router
from app.api.routes_trip import router as trip_router


def create_app() -> FastAPI:
    app = FastAPI(title="ZoeyAgent")
    app.include_router(health_router)
    app.include_router(trip_router)
    return app


app = create_app()
