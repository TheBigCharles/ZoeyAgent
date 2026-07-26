"""Embedding client used by LangGraph long-term memory indexing."""

from __future__ import annotations

from typing import Any

import httpx


class EmbeddingService:
    def __init__(self, settings: Any, http_client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.provider = getattr(settings, "embedding_provider", "ollama")
        self.base_url = str(settings.embedding_base_url).rstrip("/")
        self.model = settings.embedding_model
        self.dims = int(settings.embedding_dims)
        self.api_key = getattr(settings, "embedding_api_key", None)
        self._client = http_client or httpx.Client(timeout=30)
        self._owns_client = http_client is None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        provider = self.provider.lower()
        if provider == "ollama":
            embeddings = self._embed_with_ollama(texts)
        elif provider in {"openai", "openai_compatible", "vllm"}:
            embeddings = self._embed_with_openai_compatible(texts)
        else:
            raise ValueError(f"Unsupported embedding provider: {self.provider}")

        self._validate_dimensions(embeddings)
        return embeddings

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _embed_with_ollama(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
        )
        response.raise_for_status()
        payload = response.json()
        if "embeddings" in payload:
            return payload["embeddings"]
        if "embedding" in payload:
            return [payload["embedding"]]
        raise ValueError("Ollama embedding response did not include embeddings")

    def _embed_with_openai_compatible(self, texts: list[str]) -> list[list[float]]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = self._client.post(
            f"{self.base_url}/embeddings",
            headers=headers,
            json={"model": self.model, "input": texts},
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("OpenAI-compatible embedding response did not include data")
        return [item["embedding"] for item in data]

    def _validate_dimensions(self, embeddings: list[list[float]]) -> None:
        for embedding in embeddings:
            if len(embedding) != self.dims:
                raise ValueError(
                    f"Embedding dimensions mismatch: expected {self.dims}, got {len(embedding)}"
                )
