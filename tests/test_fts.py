import pytest

from memory.sqlite_store import SQLiteStore


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(tmp_path / "db.sqlite")
    yield s
    s.close()


def _record(store, project_id, prompt, response, **kwargs):
    return store.record_interaction(
        project_id=project_id, task_type="edit", provider="ollama",
        model="m", prompt=prompt, response=response, status="approved", **kwargs
    )


def test_fts_finds_by_keyword_in_prompt(store):
    p = store.get_or_create_project("app", "/tmp/app")
    iid = _record(store, p, "corrigir bug de autenticacao no login google", "feito")
    _record(store, p, "adicionar tela de configuracoes", "ok")

    hits = store.fts_search("autenticacao")
    assert [h["id"] for h in hits] == [iid]


def test_fts_finds_by_keyword_in_response(store):
    p = store.get_or_create_project("app", "/tmp/app")
    iid = _record(store, p, "pergunta generica", "a solucao usa Riverpod com ConsumerWidget")
    assert store.fts_search("riverpod")[0]["id"] == iid


def test_fts_stays_in_sync_after_update(store):
    p = store.get_or_create_project("app", "/tmp/app")
    iid = _record(store, p, "prompt inicial", "resposta xyzunica")
    store.update_interaction(iid, response="resposta atualizada abcunica")

    assert store.fts_search("xyzunica") == []
    assert store.fts_search("abcunica")[0]["id"] == iid


def test_fts_filters_by_project(store):
    p1 = store.get_or_create_project("app1", "/tmp/app1")
    p2 = store.get_or_create_project("app2", "/tmp/app2")
    _record(store, p1, "palavra compartilhada aqui", "r")
    _record(store, p2, "palavra compartilhada ali", "r")

    assert len(store.fts_search("compartilhada")) == 2
    assert len(store.fts_search("compartilhada", project="app1")) == 1


def test_fts_survives_special_characters(store):
    p = store.get_or_create_project("app", "/tmp/app")
    _record(store, p, "prompt qualquer", "resposta")
    # operadores soltos que quebrariam a sintaxe do MATCH → não deve levantar
    assert store.fts_search('login "google (oauth) AND -teste') is not None
