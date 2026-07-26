import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.config import AppDependencies
from app.memory.store import LongTermMemoryStore
from app.schemas.memory import MemoryCandidate
from app.services.embedding_service import EmbeddingService


def test_docker_postgres_accepts_connections_and_has_pgvector() -> None:
    if os.getenv("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Set RUN_DOCKER_TESTS=1 to verify Docker Postgres communication.")

    postgres_url = os.getenv(
        "POSTGRES_URL",
        "postgresql://zoey:zoey@127.0.0.1:5432/zoey_agent",
    )

    with psycopg.connect(postgres_url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("select 1")
            assert cursor.fetchone() == (1,)

            cursor.execute("select extname from pg_extension where extname = 'vector'")
            assert cursor.fetchone() == ("vector",)


def test_langgraph_postgres_store_round_trips_memory_with_ollama() -> None:
    if os.getenv("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Set RUN_DOCKER_TESTS=1 to verify real PostgresStore and Ollama embeddings.")

    settings = Settings(
        MEMORY_ENABLED=True,
        POSTGRES_URL=os.getenv("POSTGRES_URL", "postgresql://zoey:zoey@127.0.0.1:5432/zoey_agent"),
        EMBEDDING_PROVIDER=os.getenv("EMBEDDING_PROVIDER", "ollama"),
        EMBEDDING_BASE_URL=os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434"),
        EMBEDDING_MODEL=os.getenv("EMBEDDING_MODEL", "bge-m3:567m"),
        EMBEDDING_DIMS=int(os.getenv("EMBEDDING_DIMS", "1024")),
    )
    memory_store = LongTermMemoryStore(
        settings=settings,
        embedding_service=EmbeddingService(settings=settings),
        search_limit=3,
    )
    user_id = f"docker-memory-{uuid.uuid4().hex}"
    text = f"用户偏好轻松节奏和历史文化景点 {uuid.uuid4().hex}"

    async def run() -> list[dict]:
        await memory_store.start()
        try:
            await memory_store.save_candidates(
                user_id,
                [
                    MemoryCandidate(
                        target="semantic",
                        text=text,
                        reason="integration test",
                        confidence=0.99,
                    )
                ],
            )
            return await memory_store.search_semantic(user_id, "轻松 历史文化", limit=3)
        finally:
            await memory_store.close()

    import asyncio

    results = asyncio.run(run())

    assert any(result["text"] == text for result in results)


def test_memory_debug_endpoint_queries_real_postgres_store() -> None:
    if os.getenv("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Set RUN_DOCKER_TESTS=1 to verify memory debug endpoint with real store.")

    settings = Settings(
        MEMORY_ENABLED=True,
        POSTGRES_URL=os.getenv("POSTGRES_URL", "postgresql://zoey:zoey@127.0.0.1:5432/zoey_agent"),
        EMBEDDING_PROVIDER=os.getenv("EMBEDDING_PROVIDER", "ollama"),
        EMBEDDING_BASE_URL=os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434"),
        EMBEDDING_MODEL=os.getenv("EMBEDDING_MODEL", "bge-m3:567m"),
        EMBEDDING_DIMS=int(os.getenv("EMBEDDING_DIMS", "1024")),
    )
    memory_store = LongTermMemoryStore(
        settings=settings,
        embedding_service=EmbeddingService(settings=settings),
        search_limit=3,
    )
    user_id = f"debug-endpoint-{uuid.uuid4().hex}"
    text = f"用户偏好轻松节奏的北京历史文化行程 {uuid.uuid4().hex}"

    async def fake_dependencies() -> AppDependencies:
        return AppDependencies(graph=object(), store=memory_store)

    with TestClient(create_app(dependency_factory=fake_dependencies)) as client:
        import asyncio

        asyncio.run(
            client.app.state.dependencies.store.save_candidates(
                user_id,
                [
                    MemoryCandidate(
                        target="semantic",
                        text=text,
                        reason="integration endpoint test",
                        confidence=0.99,
                    )
                ],
            )
        )
        response = client.get(
            "/api/memory/semantic",
            params={"user_id": user_id, "query": "轻松 历史文化", "limit": 3},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["memory_type"] == "semantic"
    assert any(item["text"] == text for item in payload["items"])
