"""Recall com stores fakes: proveniência obrigatória em todo resultado."""

import pytest

from memory.retriever import Retriever
from memory.sqlite_store import SQLiteStore


class FakeEmbedder:
    model = "fake-embed"

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class FakeVectorStore:
    def __init__(self, hits):
        self.hits = hits

    def query(self, embedding, k=5, where=None):
        return self.hits[:k]


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(tmp_path / "db.sqlite")
    yield s
    s.close()


def test_recall_returns_sources_for_code_and_interactions(store):
    hits = [
        {
            "id": "code:p:src/app.py:1",
            "text": "def login(): ...",
            "distance": 0.2,
            "metadata": {
                "type": "code_chunk", "file": "src/app.py",
                "start_line": 1, "end_line": 40,
                "timestamp": "2026-07-07T10:00:00",
            },
        },
        {
            "id": "interaction:7:0",
            "text": "como implementei login google",
            "distance": 0.8,
            "metadata": {
                "type": "interaction", "interaction_id": 7,
                "tags": "auth,bugfix", "timestamp": "2026-07-01T09:00:00",
            },
        },
    ]
    retriever = Retriever(FakeVectorStore(hits), FakeEmbedder(), store)
    results = retriever.recall("login google", k=5)

    assert results[0].source == "src/app.py:1-40"
    assert results[0].type == "code_chunk"
    assert results[1].source == "interação #7"
    assert results[1].tags == ["auth", "bugfix"]
    # score decrescente com a distância
    assert results[0].score > results[1].score
    # todo resultado tem fonte e data — nunca resposta sem proveniência
    for result in results:
        assert result.source
        assert result.timestamp


def test_recall_keyword_fallback_uses_fts(store):
    p = store.get_or_create_project("app", "/tmp/app")
    iid = store.record_interaction(
        project_id=p, task_type="edit", provider="ollama", model="m",
        prompt="erro de autenticacao google", response="corrigido com refresh token",
        status="approved",
    )
    retriever = Retriever(None, FakeEmbedder(), store)
    results = retriever.recall_keyword("autenticacao", k=5)
    assert results[0].source == f"interação #{iid}"
    assert "refresh token" in results[0].snippet
