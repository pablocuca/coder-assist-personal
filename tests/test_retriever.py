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


class OrderedFakeVectorStore:
    """Vetorial que retorna hits em ordem fixa, para testar a fusão RRF."""

    def __init__(self, sources):
        self.sources = sources

    def query(self, embedding, k=5, where=None):
        return [
            {
                "id": f"v{i}",
                "text": f"conteudo de {source}",
                "distance": 0.1 * (i + 1),
                "metadata": {
                    "type": "interaction",
                    "interaction_id": source,
                    "timestamp": "2026-07-07T00:00:00",
                },
            }
            for i, source in enumerate(self.sources[:k])
        ]


def test_rrf_fuses_and_boosts_sources_in_both_lists(store):
    p = store.get_or_create_project("app", "/tmp/app")
    # interação 100 aparece no FTS (keyword) E no vetorial → deve subir ao topo
    ids = {}
    for marker in ("umaquery destaque", "outra coisa", "mais outra"):
        ids[marker] = store.record_interaction(
            project_id=p, task_type="ask", provider="ollama", model="m",
            prompt=f"pergunta sobre {marker}", response="r", status="ok",
        )
    shared = ids["umaquery destaque"]
    # vetorial: shared em 2º lugar; keyword: shared é o único resultado
    vectors = OrderedFakeVectorStore([999, shared, 998])
    retriever = Retriever(vectors, FakeEmbedder(), store)

    results = retriever.recall_hybrid("umaquery", k=3)
    assert results[0].source == f"interação #{shared}"
    # fontes deduplicadas
    assert len({r.source for r in results}) == len(results)


def test_rrf_scores_decrease(store):
    vectors = OrderedFakeVectorStore([1, 2, 3])
    retriever = Retriever(vectors, FakeEmbedder(), store)
    results = retriever.recall_hybrid("qualquer", k=3)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_synthesis_prompt_numbers_sources(store):
    vectors = OrderedFakeVectorStore([7, 8])
    retriever = Retriever(vectors, FakeEmbedder(), store)
    hits = retriever.recall_hybrid("q", k=2)
    prompt = retriever.build_synthesis_prompt("por que X?", hits)
    assert "[1]" in prompt and "[2]" in prompt
    assert "interação #7" in prompt
    assert "por que X?" in prompt
