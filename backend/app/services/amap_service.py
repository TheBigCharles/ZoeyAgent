"""Amap MCP service boundary and provider-response normalization."""

from __future__ import annotations

import json
import os
import re
import shlex
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import date as Date
from typing import Any, Literal

from app.config import Settings, StructuredAppError, TOOL_CALL_FAILED, exception_details
from app.schemas.domain import Attraction, Hotel, Location, WeatherInfo


AMAP_SOURCE = "amap"
TEXT_SEARCH_TOOL = "maps_text_search"
WEATHER_TOOL = "maps_weather"
ROUTE_TOOLS = {
    "walking": "maps_direction_walking_by_address",
    "driving": "maps_direction_driving_by_address",
    "transit": "maps_direction_transit_integrated_by_address",
}


@dataclass(slots=True)
class AmapMCPService:
    settings: Settings
    client: Any | None = None
    started: bool = False
    _session: Any | None = None
    _exit_stack: AsyncExitStack | None = None

    async def start(self) -> None:
        """Mark the service ready; the stdio MCP session is opened lazily on first call."""
        self.started = True

    async def close(self) -> None:
        """Close the shared Amap MCP client/server resources."""
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._session = None
        self._exit_stack = None
        self.started = False

    async def search_attractions(self, keywords: str, city: str | None = None) -> list[Attraction]:
        payload = await self._call_tool(
            TEXT_SEARCH_TOOL,
            _without_none({"keywords": keywords, "city": city, "citylimit": "true"}),
        )
        return [self._poi_to_attraction(poi) for poi in _extract_pois(payload)]

    async def search_hotels(self, keywords: str, city: str | None = None) -> list[Hotel]:
        payload = await self._call_tool(
            TEXT_SEARCH_TOOL,
            _without_none({"keywords": keywords, "city": city, "citylimit": "true"}),
        )
        return [self._poi_to_hotel(poi) for poi in _extract_pois(payload)]

    async def get_weather(self, city: str) -> list[WeatherInfo]:
        payload = await self._call_tool(WEATHER_TOOL, {"city": city})
        return self._normalize_weather(payload)

    async def get_route_summary(
        self,
        origin_address: str,
        destination_address: str,
        mode: Literal["walking", "driving", "transit"],
        origin_city: str | None = None,
        destination_city: str | None = None,
    ) -> dict[str, Any]:
        tool_name = ROUTE_TOOLS[mode]
        payload = await self._call_tool(
            tool_name,
            _without_none(
                {
                    "origin_address": origin_address,
                    "destination_address": destination_address,
                    "origin_city": origin_city,
                    "destination_city": destination_city,
                }
            ),
        )
        summary = _extract_route_summary(payload)
        return {
            "route_distance_km": summary["route_distance_km"],
            "route_duration_minutes": summary["route_duration_minutes"],
            "transit_method": mode,
        }

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await (await self._mcp_client()).call_tool(name, arguments)
        except StructuredAppError:
            raise
        except Exception as exc:
            raise StructuredAppError(
                code=TOOL_CALL_FAILED,
                message="Amap MCP tool call failed",
                details={"tool": name, **exception_details(exc)},
            ) from exc
        return _coerce_tool_payload(result)

    async def _mcp_client(self) -> Any:
        if self.client is not None:
            return self.client
        if self._session is not None:
            return self._session
        if not self.settings.amap_api_key:
            raise StructuredAppError(
                code=TOOL_CALL_FAILED,
                message="AMAP_MAPS_API_KEY is required before calling Amap MCP tools",
                details={"missing_env": "AMAP_MAPS_API_KEY"},
            )

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise StructuredAppError(
                code=TOOL_CALL_FAILED,
                message="MCP Python client is required before calling Amap MCP tools",
                details=exception_details(exc),
            ) from exc

        env = dict(os.environ)
        env["AMAP_MAPS_API_KEY"] = self.settings.amap_api_key
        server_params = StdioServerParameters(
            command=self.settings.amap_mcp_command,
            args=shlex.split(self.settings.amap_mcp_args),
            env=env,
        )
        stack = AsyncExitStack()
        read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()

        self._exit_stack = stack
        self._session = session
        self.started = True
        return session

    def _poi_to_attraction(self, poi: dict[str, Any]) -> Attraction:
        biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
        return Attraction(
            name=str(poi.get("name") or ""),
            city=_optional_str(poi.get("cityname") or poi.get("city")),
            address=str(poi.get("address") or ""),
            location=_parse_location(poi.get("location")),
            description=str(poi.get("type") or ""),
            category=str(poi.get("type") or "attraction"),
            rating=_parse_float(biz_ext.get("rating") or poi.get("rating")),
            ticket_price=_parse_int(biz_ext.get("cost") or poi.get("cost")),
            poi_id=_optional_str(poi.get("id")),
            source=AMAP_SOURCE,
        )

    def _poi_to_hotel(self, poi: dict[str, Any]) -> Hotel:
        biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
        return Hotel(
            name=str(poi.get("name") or ""),
            city=_optional_str(poi.get("cityname") or poi.get("city")),
            address=str(poi.get("address") or ""),
            location=_parse_location(poi.get("location")),
            rating=_parse_float(biz_ext.get("rating") or poi.get("rating")),
            distance=str(poi.get("distance") or ""),
            type=str(poi.get("type") or ""),
            estimated_cost=_parse_int(biz_ext.get("cost") or poi.get("cost")),
            poi_id=_optional_str(poi.get("id")),
            source=AMAP_SOURCE,
        )

    def _normalize_weather(self, payload: dict[str, Any]) -> list[WeatherInfo]:
        weather: list[WeatherInfo] = []
        for forecast in payload.get("forecasts", []):
            city = str(forecast.get("city") or payload.get("city") or "")
            casts = forecast.get("casts") if isinstance(forecast.get("casts"), list) else [forecast]
            for cast in casts:
                if "date" not in cast:
                    continue
                weather.append(_cast_to_weather_info(cast=cast, city=city))
        return weather


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_location(value: Any) -> Location | None:
    if not value:
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 2:
            return None
        return Location(longitude=float(parts[0]), latitude=float(parts[1]))
    if isinstance(value, dict):
        longitude = value.get("longitude") or value.get("lng") or value.get("lon")
        latitude = value.get("latitude") or value.get("lat")
        if longitude is None or latitude is None:
            return None
        return Location(longitude=float(longitude), latitude=float(latitude))
    return None


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        return float(match.group()) if match else None


def _parse_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, int):
        return value
    match = re.search(r"-?\d+", str(value))
    return int(match.group()) if match else 0


def _extract_pois(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pois = payload.get("pois", [])
    return pois if isinstance(pois, list) else []


def _extract_route_summary(payload: dict[str, Any]) -> dict[str, Any]:
    route = payload.get("route", {})
    candidates = route.get("paths") or route.get("transits") or []
    first = candidates[0] if candidates else {}
    distance_meters = _parse_float(first.get("distance"))
    duration_seconds = _parse_float(first.get("duration"))
    return {
        "route_distance_km": round(distance_meters / 1000, 3) if distance_meters is not None else None,
        "route_duration_minutes": round(duration_seconds / 60) if duration_seconds is not None else None,
    }


def _cast_to_weather_info(cast: dict[str, Any], city: str) -> WeatherInfo:
    return WeatherInfo(
        city=city,
        date=Date.fromisoformat(str(cast["date"])),
        day_weather=str(cast.get("dayweather") or ""),
        night_weather=str(cast.get("nightweather") or ""),
        day_temp=_parse_int(cast.get("daytemp")),
        night_temp=_parse_int(cast.get("nighttemp")),
        wind_direction=str(cast.get("daywind") or ""),
        wind_power=str(cast.get("daypower") or ""),
    )


def _coerce_tool_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        if "content" in result:
            return _coerce_content_payload(result["content"])
        return result
    if hasattr(result, "model_dump"):
        return _coerce_tool_payload(result.model_dump(mode="json"))
    if hasattr(result, "content"):
        return _coerce_content_payload(result.content)
    raise TypeError(f"Unsupported MCP tool result type: {type(result).__name__}")


def _coerce_content_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        for item in content:
            text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
            if text:
                return json.loads(text)
    if isinstance(content, str):
        return json.loads(content)
    raise TypeError(f"Unsupported MCP content type: {type(content).__name__}")
