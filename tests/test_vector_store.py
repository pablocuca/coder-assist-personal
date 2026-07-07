"""Integração real com ChromaDB persistente (sem rede — vetores fornecidos)."""

import pytest

chromadb = pytest.importorskip("chromadb")

from memory.vector_store import VectorStore  # noqa: E402


@pytest.fixture
def vectors(tmp_path):
    return VectorStore(tmp_path / "estado", "meu-projeto")


def _meta(file, **extra):
    return {"type": "code_chunk", "project": "meu-projeto", "file": file, **extra}


def test_upsert_query_roundtrip(vectors):
    vectors.upsert(
        ids=["a", "b"],
        texts=["def login(): pass", "def logout(): pass"],
        embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        metadatas=[_meta("auth.py"), _meta("sair.py")],
    )
    hits = vectors.query([1.0, 0.0, 0.0], k=1)
    assert hits[0]["id"] == "a"
    assert hits[0]["metadata"]["file"] == "auth.py"
    assert hits[0]["distance"] < 0.01


def test_delete_by_file_invalidates_chunks(vectors):
    vectors.upsert(
        ids=["a", "b"],
        texts=["um", "dois"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        metadatas=[_meta("velho.py"), _meta("mantem.py")],
    )
    vectors.delete_by_file("velho.py")
    assert vectors.count() == 1
    hits = vectors.query([1.0, 0.0], k=5)
    assert all(h["metadata"]["file"] != "velho.py" for h in hits)


def test_upsert_replaces_same_id(vectors):
    vectors.upsert(["x"], ["antigo"], [[1.0, 0.0]], [_meta("f.py")])
    vectors.upsert(["x"], ["novo"], [[1.0, 0.0]], [_meta("f.py")])
    assert vectors.count() == 1
    assert vectors.query([1.0, 0.0], k=1)[0]["text"] == "novo"


def test_collection_name_sanitized(tmp_path):
    # nomes com espaços/acentos não podem quebrar o chroma
    vs = VectorStore(tmp_path / "estado", "Projeto Água & Fogo!")
    vs.upsert(["i"], ["t"], [[0.5, 0.5]], [_meta("a.py")])
    assert vs.count() == 1
