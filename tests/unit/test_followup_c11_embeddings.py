from __future__ import annotations

import json

import httpx

from seldon.config import OpenRouterConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.repositories import KBRepository
from seldon.kb.vector import EmbeddingResult, LocalHashEmbeddingProvider, OpenRouterEmbeddingProvider, pgvector_literal


class FakeEmbeddingProvider:
    backend = "fake"

    def __init__(self):
        self.calls: list[str] = []

    def embed(self, text: str) -> EmbeddingResult:
        self.calls.append(text)
        if "gold" in text.lower():
            return EmbeddingResult([1.0, 0.0, 0.0], {"backend": self.backend, "model": "fake-3d", "dimensions": 3})
        return EmbeddingResult([0.0, 1.0, 0.0], {"backend": self.backend, "model": "fake-3d", "dimensions": 3})


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def test_kb_repository_uses_embedding_provider_for_writes_and_sqlite_search_fallback():
    provider = FakeEmbeddingProvider()
    factory = session_factory()
    with factory() as db:
        with db.begin():
            kb = KBRepository(db, embedding_provider=provider)
            gold = kb.create_entry(content="Gold demand rises as rates fall", source_name="Seed", topics=["gold"])
            oil = kb.create_entry(content="Oil shipping costs rise", source_name="Seed", topics=["oil"])
            ranked = kb.semantic_search("gold rate demand", limit=2)

        assert gold.content_embedding == [1.0, 0.0, 0.0]
        assert gold.embedding_metadata == {"backend": "fake", "model": "fake-3d", "dimensions": 3}
        assert oil.content_embedding == [0.0, 1.0, 0.0]
        assert ranked[0].id == gold.id
        assert provider.calls == ["Gold demand rises as rates fall", "Oil shipping costs rise", "gold rate demand"]


def test_openrouter_embedding_provider_calls_openai_compatible_embeddings_endpoint():
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append({"url": str(request.url), "headers": dict(request.headers), "body": json.loads(request.content)})
        return httpx.Response(200, json={"model": "text-embedding-test", "data": [{"embedding": [0.1, 0.2, 0.3]}], "usage": {"prompt_tokens": 4}})

    cfg = OpenRouterConfig(base_url="https://openrouter.test/api/v1", embedding_model="text-embedding-test", app_name="The Seldon Project")
    provider = OpenRouterEmbeddingProvider(cfg, api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = provider.embed("embed this")

    assert result.vector == [0.1, 0.2, 0.3]
    assert result.metadata["backend"] == "openrouter_embeddings"
    assert result.metadata["model"] == "text-embedding-test"
    assert result.metadata["dimensions"] == 3
    assert requests[0]["url"] == "https://openrouter.test/api/v1/embeddings"
    assert requests[0]["body"] == {"model": "text-embedding-test", "input": "embed this"}
    assert requests[0]["headers"]["authorization"] == "Bearer test-key"


def test_pgvector_migration_and_literal_define_production_vector_path():
    migration = open("alembic/versions/0002_pgvector_embeddings.py", encoding="utf-8").read()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "content_embedding_vector vector(1536)" in migration
    assert "USING ivfflat" in migration
    assert "vector_cosine_ops" in migration
    assert pgvector_literal([0.1, 0.25, -1.0]) == "[0.1,0.25,-1]"


def test_local_hash_embedding_provider_keeps_sqlite_fallback_deterministic():
    provider = LocalHashEmbeddingProvider(dims=8)
    first = provider.embed("same text")
    second = provider.embed("same text")
    assert first.vector == second.vector
    assert first.metadata == {"backend": "local_hash", "dimensions": 8}
    assert len(first.vector) == 8
