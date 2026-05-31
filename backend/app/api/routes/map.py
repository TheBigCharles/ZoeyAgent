"""Map-related routes reserved for future Amap integration."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/map", tags=["map"])
