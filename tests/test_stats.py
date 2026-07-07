import pytest

from memory.sqlite_store import SQLiteStore


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(tmp_path / "db.sqlite")
    yield s
    s.close()


def test_stats_totals_and_providers(store):
    p = store.get_or_create_project("app", "/tmp/app")
    store.record_interaction(
        project_id=p, task_type="edit", provider="ollama", model="qwen",
        prompt="p1", status="approved", input_tokens=100, output_tokens=50,
        duration_ms=800, cost_estimate=0.0,
    )
    store.record_interaction(
        project_id=p, task_type="edit", provider="ollama", model="qwen",
        prompt="p2", status="rejected", input_tokens=200, output_tokens=80,
        duration_ms=1200, cost_estimate=0.0,
    )
    store.record_interaction(
        project_id=p, task_type="edit", provider="claude", model="sonnet",
        prompt="p3", status="provider_error", cost_estimate=0.12,
    )

    data = store.stats()
    assert data["totals"]["prompts"] == 3
    assert data["totals"]["tokens_in"] == 300
    assert data["totals"]["tokens_out"] == 130
    assert data["totals"]["cost"] == pytest.approx(0.12)

    ollama = next(r for r in data["by_provider"] if r["provider"] == "ollama")
    assert ollama["uses"] == 2
    assert ollama["successes"] == 1  # approved conta, rejected não
    assert ollama["avg_ms"] == 1000

    edits = data["edits"]
    assert edits["total_edits"] == 3
    assert edits["approved"] == 1
    assert edits["rejected"] == 1
    assert edits["claude_calls"] == 1


def test_stats_since_filter_excludes_old(store):
    p = store.get_or_create_project("app", "/tmp/app")
    iid = store.record_interaction(
        project_id=p, task_type="ask", provider="ollama", model="m",
        prompt="antiga", status="ok",
    )
    # envelhece a interação diretamente no banco
    store.conn.execute(
        "UPDATE interactions SET timestamp = '2020-01-01 00:00:00' WHERE id = ?", (iid,)
    )
    store.conn.commit()
    store.record_interaction(
        project_id=p, task_type="ask", provider="ollama", model="m",
        prompt="recente", status="ok",
    )

    assert store.stats()["totals"]["prompts"] == 2
    assert store.stats(since="2024-01-01 00:00:00")["totals"]["prompts"] == 1


def test_stats_project_filter(store):
    p1 = store.get_or_create_project("app1", "/tmp/app1")
    p2 = store.get_or_create_project("app2", "/tmp/app2")
    store.record_interaction(project_id=p1, task_type="ask", provider="ollama",
                             model="m", prompt="a", status="ok")
    store.record_interaction(project_id=p2, task_type="ask", provider="ollama",
                             model="m", prompt="b", status="ok")

    assert store.stats(project="app1")["totals"]["prompts"] == 1
    assert store.stats(project="app1")["top_projects"] == [
        {"name": "app1", "interactions": 1}
    ]


def test_record_commit(store):
    p = store.get_or_create_project("app", "/tmp/app")
    iid = store.record_interaction(project_id=p, task_type="commit_message",
                                   provider="ollama", model="m", prompt="diff", status="ok")
    cid = store.record_commit(p, "abc123", "main", "Corrige bug", iid)
    row = store.conn.execute("SELECT * FROM commits WHERE id = ?", (cid,)).fetchone()
    assert row["hash"] == "abc123"
    assert row["interaction_id"] == iid
