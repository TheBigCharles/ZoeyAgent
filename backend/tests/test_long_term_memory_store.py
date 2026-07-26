import asyncio
from types import SimpleNamespace

from app.memory.store import LongTermMemoryStore
from app.schemas.memory import MemoryCandidate


class FakePostgresStore:
    def __init__(self) -> None:
        self.setup_called = False
        self.put_calls: list[dict] = []
        self.search_calls: list[dict] = []

    def setup(self) -> None:
        self.setup_called = True

    def put(self, namespace, key, value, index=None):
        self.put_calls.append(
            {
                "namespace": namespace,
                "key": key,
                "value": value,
                "index": index,
            }
        )

    def search(self, namespace_prefix, *, query=None, limit=10, **_):
        self.search_calls.append(
            {
                "namespace_prefix": namespace_prefix,
                "query": query,
                "limit": limit,
            }
        )
        return [
            SimpleNamespace(
                key="memory-001",
                value={"text": "用户偏好轻松节奏", "target": "semantic"},
                score=0.93,
            )
        ]


def test_long_term_memory_store_saves_candidates_to_target_namespaces() -> None:
    fake_store = FakePostgresStore()
    memory_store = LongTermMemoryStore(store=fake_store)

    candidates = [
        MemoryCandidate(target="semantic", text="用户偏好轻松节奏", reason="preference", confidence=0.9),
        MemoryCandidate(target="episodic", text="用户上次选择了市中心酒店", reason="decision", confidence=0.8),
        MemoryCandidate(target="discard", text="Amap returned 10 records", reason="tool noise", confidence=1.0),
    ]

    saved_count = asyncio.run(memory_store.save_candidates("user-001", candidates))

    assert saved_count == 2
    assert fake_store.put_calls[0]["namespace"] == ("user-001", "semantic_memories")
    assert fake_store.put_calls[0]["index"] == ["text"]
    assert fake_store.put_calls[1]["namespace"] == ("user-001", "episodic_memories")


def test_long_term_memory_store_searches_semantic_and_episodic_memories() -> None:
    fake_store = FakePostgresStore()
    memory_store = LongTermMemoryStore(store=fake_store, search_limit=4)

    semantic = asyncio.run(memory_store.search_semantic("user-001", "轻松北京行程"))
    episodic = asyncio.run(memory_store.search_episodic("user-001", "酒店选择"))

    assert semantic[0]["text"] == "用户偏好轻松节奏"
    assert semantic[0]["score"] == 0.93
    assert fake_store.search_calls[0] == {
        "namespace_prefix": ("user-001", "semantic_memories"),
        "query": "轻松北京行程",
        "limit": 4,
    }
    assert fake_store.search_calls[1]["namespace_prefix"] == ("user-001", "episodic_memories")
    assert episodic[0]["key"] == "memory-001"
