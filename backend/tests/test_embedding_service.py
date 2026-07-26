import httpx
import pytest

from app.config import Settings
from app.services.embedding_service import EmbeddingService


def make_settings() -> Settings:
    return Settings(
        EMBEDDING_PROVIDER="ollama",
        EMBEDDING_BASE_URL="http://embedding.test",
        EMBEDDING_MODEL="bge-m3:567m",
        EMBEDDING_DIMS=3,
    )


def test_ollama_embedding_service_returns_vectors_and_posts_expected_payload() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            {
                "url": str(request.url),
                "json": request.read().decode("utf-8"),
            }
        )
        return httpx.Response(
            200,
            json={
                "model": "bge-m3:567m",
                "embeddings": [
                    [0.1, 0.2, 0.3],
                    [0.4, 0.5, 0.6],
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = EmbeddingService(settings=make_settings(), http_client=client)

    embeddings = service.embed_texts(["用户偏好轻松节奏", "历史文化景点"])

    assert embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert requests[0]["url"] == "http://embedding.test/api/embed"
    assert '"model":"bge-m3:567m"' in requests[0]["json"]
    assert '"input":["用户偏好轻松节奏","历史文化景点"]' in requests[0]["json"]


def test_embedding_service_rejects_unexpected_dimensions() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = EmbeddingService(settings=make_settings(), http_client=client)

    with pytest.raises(ValueError, match="Embedding dimensions mismatch"):
        service.embed_texts(["too short"])
