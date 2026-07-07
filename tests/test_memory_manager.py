"""Indexação incremental com embedder fake e vetorial fake — sem rede, sem chroma."""

import pytest

from core.settings import Settings
from memory.memory_manager import MemoryManager
from memory.sqlite_store import SQLiteStore


class FakeEmbedder:
    model = "fake-embed"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[float(len(t)), 0.0, 1.0] for t in texts]


class FakeVectorStore:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.deleted_files: list[str] = []

    def upsert(self, ids, texts, embeddings, metadatas):
        for i, item_id in enumerate(ids):
            self.docs[item_id] = {"text": texts[i], "metadata": metadatas[i]}

    def delete_by_file(self, rel_path):
        self.deleted_files.append(rel_path)
        self.docs = {
            k: v for k, v in self.docs.items()
            if v["metadata"].get("file") != rel_path
        }

    def count(self):
        return len(self.docs)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "projeto"
    root.mkdir()
    (root / "app.py").write_text("def main():\n    print('oi')\n")
    (root / "notas.md").write_text("# Decisões\nUsar Riverpod.\n")
    (root / "imagem.png").write_bytes(b"\x89PNG\x00\x00binario")  # byte nulo → pular
    (root / "grande.py").write_text("x = 1\n" * 100_000)          # > max_indexed_file_kb
    (root / "ignorado.py").write_text("segredo = 1\n")
    (root / ".gitignore").write_text("ignorado.py\nbuild/\n")
    build = root / "build"
    build.mkdir()
    (build / "gerado.py").write_text("gerado = True\n")
    return root


@pytest.fixture
def manager(project, tmp_path):
    settings = Settings(state_dir=tmp_path / "estado")
    store = SQLiteStore(tmp_path / "db.sqlite")
    project_id = store.get_or_create_project("projeto", str(project))
    m = MemoryManager(settings, store, project, project_id, "projeto")
    m.embedder = FakeEmbedder()
    m._vectors = FakeVectorStore()
    yield m
    store.close()


def test_index_respects_gitignore_binary_and_size(manager):
    report = manager.index_project()
    indexed_files = {
        v["metadata"]["file"] for v in manager._vectors.docs.values()
    }
    assert "app.py" in indexed_files
    assert "notas.md" in indexed_files
    assert "ignorado.py" not in indexed_files      # .gitignore real
    assert "build/gerado.py" not in indexed_files  # .gitignore de diretório
    assert "imagem.png" not in indexed_files       # binário (e extensão fora do include)
    assert "grande.py" not in indexed_files        # acima de max_indexed_file_kb
    assert report.indexed_files == 2
    assert report.skipped >= 1


def test_incremental_skips_unchanged_and_reindexes_changed(manager, project):
    first = manager.index_project()
    assert first.indexed_files == 2

    second = manager.index_project()
    assert second.indexed_files == 0
    assert second.unchanged == 2

    (project / "app.py").write_text("def main():\n    print('mudou')\n")
    third = manager.index_project()
    assert third.indexed_files == 1
    assert third.unchanged == 1
    # invalidação: chunks antigos do arquivo foram removidos antes dos novos
    assert "app.py" in manager._vectors.deleted_files


def test_full_reindexes_everything(manager):
    manager.index_project()
    report = manager.index_project(full=True)
    assert report.indexed_files == 2
    assert report.unchanged == 0


def test_metadata_follows_section_12(manager):
    manager.index_project()
    doc = next(
        v for v in manager._vectors.docs.values()
        if v["metadata"]["file"] == "app.py"
    )
    meta = doc["metadata"]
    assert meta["type"] == "code_chunk"
    assert meta["project"] == "projeto"
    assert meta["embedding_model"] == "fake-embed"
    assert meta["file_hash"]
    assert meta["start_line"] == 1


def test_index_interaction_best_effort(manager):
    manager.index_interaction(42, "como fiz o login?", "com oauth do google")
    docs = [
        v for v in manager._vectors.docs.values()
        if v["metadata"]["type"] == "interaction"
    ]
    assert len(docs) == 1
    assert docs[0]["metadata"]["interaction_id"] == 42


def test_index_interaction_never_raises_without_vector_store(manager):
    class Broken:
        def upsert(self, *a, **k):
            from core.errors import VectorStoreError
            raise VectorStoreError("chroma corrompido")

        def delete_by_file(self, rel):
            pass

    manager._vectors = Broken()
    manager.index_interaction(1, "p", "r")  # não deve levantar (degrada com warning)
