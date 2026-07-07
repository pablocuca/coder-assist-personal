import pytest

from core.errors import ProviderError
from core.router import Router
from core.settings import Settings
from memory.sqlite_store import SQLiteStore
from providers.base_provider import BaseProvider, ProviderResponse

SECRET = 'api_key = "placeholder-value"'


class FakeProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def complete(self, prompt, system=None, json_mode=False):
        return ProviderResponse(
            text=f'{{"ok": true, "leak": "{SECRET}"}}',
            model="fake-model",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0,
        )


class FailingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def complete(self, prompt, system=None, json_mode=False):
        raise ProviderError(f"conexão recusada (config continha {SECRET})")


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(tmp_path / "db.sqlite")
    yield s
    s.close()


def make_router(store, provider):
    settings = Settings()
    settings.providers.default = "fake"
    project_id = store.get_or_create_project("teste", "/tmp/projeto-teste")
    return Router(
        settings, store, {"fake": provider}, project_id=project_id, git_branch="main"
    )


def test_success_records_complete_interaction(store):
    router = make_router(store, FakeProvider())
    iid, response = router.ask("edit", f"prompt com {SECRET}", system="sys")

    row = store.get_interaction(iid)
    assert row["status"] == "ok"
    assert row["provider"] == "fake"
    assert row["model"] == "fake-model"
    assert row["task_type"] == "edit"
    assert row["input_tokens"] == 10
    assert row["output_tokens"] == 5
    assert row["duration_ms"] >= 0
    assert row["git_branch"] == "main"
    assert row["project_id"] is not None


def test_secrets_redacted_in_prompt_and_response(store):
    router = make_router(store, FakeProvider())
    iid, _ = router.ask("edit", f"contexto: {SECRET}")
    row = store.get_interaction(iid)
    assert SECRET not in row["prompt"]
    assert SECRET not in row["response"]


def test_provider_error_recorded_and_reraised(store):
    router = make_router(store, FailingProvider())
    with pytest.raises(ProviderError):
        router.ask("edit", "qualquer prompt")

    iid = store.last_interaction_id()
    row = store.get_interaction(iid)
    assert row["status"] == "provider_error"
    assert SECRET not in (row["response"] or "")


def test_unknown_provider_rejected(store):
    router = make_router(store, FakeProvider())
    with pytest.raises(ProviderError, match="desconhecido"):
        router.ask("edit", "prompt", provider="inexistente")


def test_status_update_after_approval(store):
    router = make_router(store, FakeProvider())
    iid, _ = router.ask("edit", "prompt")
    store.update_interaction(iid, status="approved", confidence=0.9)
    row = store.get_interaction(iid)
    assert row["status"] == "approved"
    assert row["confidence"] == 0.9


def test_escalation_policy(store):
    router = make_router(store, FakeProvider())
    assert router.should_escalate(0.30) is True     # abaixo do limiar 0.60
    assert router.should_escalate(0.59) is True
    assert router.should_escalate(0.60) is False
    assert router.should_escalate(0.95) is False
    assert router.should_escalate(None) is True     # sem confidence declarada


def test_escalation_reasons_context_window(store):
    router = make_router(store, FakeProvider())
    window = router.settings.providers.ollama.context_window_tokens
    small = router.escalation_reasons(prompt_chars=100)
    huge = router.escalation_reasons(prompt_chars=(window + 1000) * 4)
    assert small == []
    assert any("janela" in reason for reason in huge)


def test_escalation_reasons_parse_failures_and_task_type(store):
    router = make_router(store, FakeProvider())
    assert router.escalation_reasons(parse_failures=1) == []
    assert any("falhas" in r for r in router.escalation_reasons(parse_failures=2))
    assert any(
        "complexo" in r
        for r in router.escalation_reasons(task_type="architecture_review")
    )
    assert router.escalation_reasons(task_type="edit", confidence=0.9) == []


def test_estimate_claude_cost_uses_pricing_table(store):
    router = make_router(store, FakeProvider())
    pricing = router.settings.providers.claude.pricing
    estimate = router.estimate_claude_cost(400_000)  # ~100k tokens de entrada
    expected = 100_000 / 1e6 * pricing.input_usd_per_mtok + 1500 / 1e6 * pricing.output_usd_per_mtok
    assert estimate == pytest.approx(expected)
    assert router.estimate_claude_cost(4_000) < estimate
