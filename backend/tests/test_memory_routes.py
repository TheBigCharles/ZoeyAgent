from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import AppDependencies


class FakeMemoryStore:
    def __init__(self) -> None:
        self.semantic_calls: list[dict] = []
        self.episodic_calls: list[dict] = []

    async def search_semantic(self, user_id: str, query: str | None = None, limit: int | None = None) -> list[dict]:
        self.semantic_calls.append({"user_id": user_id, "query": query, "limit": limit})
        return [{"key": "semantic-001", "text": "用户偏好轻松节奏", "score": 0.9}]

    async def search_episodic(self, user_id: str, query: str | None = None, limit: int | None = None) -> list[dict]:
        self.episodic_calls.append({"user_id": user_id, "query": query, "limit": limit})
        return [{"key": "episodic-001", "text": "用户上次选择市中心酒店", "score": 0.8}]


def test_semantic_memory_endpoint_queries_store() -> None:
    store = FakeMemoryStore()

    async def fake_dependencies() -> AppDependencies:
        return AppDependencies(graph=object(), store=store)

    with TestClient(create_app(dependency_factory=fake_dependencies)) as client:
        response = client.get(
            "/api/memory/semantic",
            params={"user_id": "user-001", "query": "轻松北京行程", "limit": 3},
        )

    assert response.status_code == 200
    assert store.semantic_calls == [{"user_id": "user-001", "query": "轻松北京行程", "limit": 3}]
    assert response.json() == {
        "memory_type": "semantic",
        "user_id": "user-001",
        "query": "轻松北京行程",
        "limit": 3,
        "count": 1,
        "items": [{"key": "semantic-001", "text": "用户偏好轻松节奏", "score": 0.9}],
    }


def test_episodic_memory_endpoint_queries_store_without_query() -> None:
    store = FakeMemoryStore()

    async def fake_dependencies() -> AppDependencies:
        return AppDependencies(graph=object(), store=store)

    with TestClient(create_app(dependency_factory=fake_dependencies)) as client:
        response = client.get("/api/memory/episodic", params={"user_id": "user-001"})

    assert response.status_code == 200
    assert store.episodic_calls == [{"user_id": "user-001", "query": None, "limit": 10}]
    assert response.json()["memory_type"] == "episodic"
    assert response.json()["count"] == 1
    assert response.json()["items"][0]["key"] == "episodic-001"


def test_memory_endpoint_returns_structured_error_when_store_is_disabled() -> None:
    async def fake_dependencies() -> AppDependencies:
        return AppDependencies(graph=object(), store=None)

    with TestClient(create_app(dependency_factory=fake_dependencies)) as client:
        response = client.get("/api/memory/semantic", params={"user_id": "user-001"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "MEMORY_STORE_UNAVAILABLE",
            "message": "Long-term memory store is not enabled",
            "details": {},
        }
    }
