"""Amap MCP service boundary.

This module will own the shared Amap MCP client process and expose normalized
methods for attraction, hotel, weather, geocoding, and route-summary calls.
"""

from dataclasses import dataclass

from app.config import Settings


@dataclass(slots=True)
class AmapMCPService:
    settings: Settings
    started: bool = False

    async def start(self) -> None:
        """Start or connect to the shared Amap MCP server."""
        self.started = True

    async def close(self) -> None:
        """Close the shared Amap MCP client/server resources."""
        self.started = False
