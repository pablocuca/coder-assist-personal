import pytest

from memory.sqlite_store import SQLiteStore


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(tmp_path / "db.sqlite")
    yield s
    s.close()


def test_pragmas_active(store):
    assert store.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_schema_version(store):
    version = store.conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version == max(SQLiteStore.MIGRATIONS)


def test_project_idempotent(store):
    a = store.get_or_create_project("app", "/tmp/app")
    b = store.get_or_create_project("app", "/tmp/app")
    assert a == b


def test_history_filters_by_project_and_tag(store):
    p1 = store.get_or_create_project("app1", "/tmp/app1")
    p2 = store.get_or_create_project("app2", "/tmp/app2")
    i1 = store.record_interaction(
        project_id=p1, task_type="edit", provider="ollama",
        model="m", prompt="p1", status="approved",
    )
    store.record_interaction(
        project_id=p2, task_type="ask", provider="ollama",
        model="m", prompt="p2", status="ok",
    )
    store.add_tag(i1, "auth")

    assert len(store.history()) == 2
    assert len(store.history(project="app1")) == 1
    assert len(store.history(tag="auth")) == 1
    assert store.history(tag="auth")[0]["id"] == i1
    assert store.history(project="app2", tag="auth") == []


def test_upsert_file_and_link(store):
    p = store.get_or_create_project("app", "/tmp/app")
    iid = store.record_interaction(
        project_id=p, task_type="edit", provider="ollama",
        model="m", prompt="p", status="approved",
    )
    f1 = store.upsert_file(p, "src/app.py", "hash1")
    f2 = store.upsert_file(p, "src/app.py", "hash2")  # mesmo arquivo, hash novo
    assert f1 == f2
    store.link_interaction_file(iid, f1)
    store.link_interaction_file(iid, f1)  # idempotente

    row = store.conn.execute(
        "SELECT hash FROM files WHERE id = ?", (f1,)
    ).fetchone()
    assert row["hash"] == "hash2"


def test_update_interaction_whitelist(store):
    p = store.get_or_create_project("app", "/tmp/app")
    iid = store.record_interaction(
        project_id=p, task_type="edit", provider="ollama",
        model="m", prompt="p", status="ok",
    )
    with pytest.raises(ValueError):
        store.update_interaction(iid, prompt="tentativa de reescrever histórico")
