"""Run the local FastAPI development server.

This script keeps startup anchored to the backend directory so `.env` and the
`app` package resolve the same way from PowerShell, VS Code, or a terminal.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


def main() -> None:
    backend_dir = Path(__file__).resolve().parent
    os.chdir(backend_dir)
    load_dotenv(backend_dir / ".env")

    from app.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
