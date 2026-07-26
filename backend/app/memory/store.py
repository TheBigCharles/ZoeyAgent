"""Long-term memory access through LangGraph PostgresStore."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import AbstractContextManager
from typing import Any

from app.schemas.memory import MemoryCandidate


SEMANTIC_NAMESPACE = "semantic_memories"
EPISODIC_NAMESPACE = "episodic_memories"


class LongTermMemoryStore:
    def __init__(
        self,
        *,
        settings: Any | None = None,
        embedding_service: Any | None = None,
        store: Any | None = None,
        search_limit: int = 5,
    ) -> None:
        self.settings = settings
        self.embedding_service = embedding_service
        self.search_limit = search_limit
        self._store = store
        self._context_manager: AbstractContextManager | None = None

    async def start(self) -> None:
        if self._store is not None:
            if hasattr(self._store, "setup"):
                await asyncio.to_thread(self._store.setup)
            return
        if self.settings is None or not getattr(self.settings, "postgres_url", None):
            raise ValueError("POSTGRES_URL is required when long-term memory is enabled")
        if self.embedding_service is None:
            raise ValueError("EmbeddingService is required when long-term memory is enabled")
        await asyncio.to_thread(self._start_sync)

    async def close(self) -> None:
        if self._context_manager is not None:
            await asyncio.to_thread(self._context_manager.__exit__, None, None, None)
            self._context_manager = None
            self._store = None
        if self.embedding_service is not None and hasattr(self.embedding_service, "close"):
            await asyncio.to_thread(self.embedding_service.close)

    async def save_candidates(self, user_id: str, candidates: list[MemoryCandidate]) -> int:
        return await asyncio.to_thread(self._save_candidates_sync, user_id, candidates)

    async def search_semantic(self, user_id: str, query: str, limit: int | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._search_sync,
            (user_id, SEMANTIC_NAMESPACE),
            query,
            limit or self.search_limit,
        )

    async def search_episodic(self, user_id: str, query: str, limit: int | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._search_sync,
            (user_id, EPISODIC_NAMESPACE),
            query,
            limit or self.search_limit,
        )

    def _start_sync(self) -> None:
        from langgraph.store.postgres import PostgresStore

        index = {
            "dims": int(self.settings.embedding_dims),
            "embed": self.embedding_service.embed_texts,
            "fields": ["text"],
        }
        self._context_manager = PostgresStore.from_conn_string(self.settings.postgres_url, index=index)
        self._store = self._context_manager.__enter__()
        self._store.setup()

    def _save_candidates_sync(self, user_id: str, candidates: list[MemoryCandidate]) -> int:
        store = self._require_store()
        saved_count = 0
        for candidate in candidates:
            if candidate.target == "discard":
                continue
            namespace = (user_id, _namespace_for_target(candidate.target))
            value = candidate.model_dump(mode="json")
            store.put(namespace, _memory_key(candidate), value, index=["text"])
            saved_count += 1
        return saved_count

    def _search_sync(self, namespace: tuple[str, str], query: str, limit: int) -> list[dict[str, Any]]:
        store = self._require_store()
        items = store.search(namespace, query=query, limit=limit)
        return [_memory_from_item(item) for item in items]

    def _require_store(self) -> Any:
        if self._store is None:
            raise RuntimeError("Long-term memory store has not been started")
        return self._store


def _namespace_for_target(target: str) -> str:
    if target == "semantic":
        return SEMANTIC_NAMESPACE
    if target == "episodic":
        return EPISODIC_NAMESPACE
    raise ValueError(f"Unsupported memory target: {target}")


def _memory_key(candidate: MemoryCandidate) -> str:
    raw = f"{candidate.target}:{candidate.text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _memory_from_item(item: Any) -> dict[str, Any]:
    value = dict(item.value)
    value["key"] = item.key
    if getattr(item, "score", None) is not None:
        value["score"] = item.score
    return value
