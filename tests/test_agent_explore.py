"""Agent._explore_context — liga a exploração só quando faz sentido, com segurança:
nunca ativa com Claude, degrada sem quebrar o edit se o Ollama falhar/faltar."""

from __future__ import annotations

import pytest

from cli.ui import UI
from core.agent import Agent
from core.context_explorer import ExplorationResult
from core.errors import ProviderError
from core.router import Router
from core.settings import Settings
from memory.sqlite_store import SQLiteStore
from providers.base_provider import BaseProvider
from providers.ollama_provider import OllamaProvider


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(tmp_path / "db.sqlite")
    yield s
    s.close()


def _agent(tmp_path, store, providers: dict) -> Agent:
    settings = Settings(state_dir=tmp_path / "state")
    project_id = store.get_or_create_project("teste", str(tmp_path))
    router = Router(settings, store, providers, project_id=project_id, git_branch="main")
    return Agent(settings, store, router, UI(), tmp_path, project_id)


class DummyClaude(BaseProvider):
    name = "claude"
    model = "claude-fake"

    def complete(self, prompt, system=None, json_mode=False):
        raise AssertionError("exploração não deveria chamar nenhum provider diretamente")


def test_explore_never_activates_for_claude_provider(tmp_path, store, monkeypatch):
    agent = _agent(
        tmp_path,
        store,
        {"ollama": OllamaProvider(Settings().providers.ollama), "claude": DummyClaude()},
    )

    def boom(*a, **kw):
        raise AssertionError("ContextExplorer não deveria ser construído para provider=claude")

    monkeypatch.setattr("core.agent.ContextExplorer", boom)
    result = agent._explore_context("app.py", "conteudo", "instrucao", provider="claude")
    assert result == {}


def test_explore_warns_and_skips_when_ollama_unavailable(tmp_path, store):
    agent = _agent(tmp_path, store, {"claude": DummyClaude()})  # sem "ollama" no dict
    result = agent._explore_context("app.py", "conteudo", "instrucao", provider=None)
    assert result == {}


def test_explore_returns_discovered_files(tmp_path, store, monkeypatch):
    agent = _agent(tmp_path, store, {"ollama": OllamaProvider(Settings().providers.ollama)})

    class FakeExplorer:
        def __init__(self, *a, **kw):
            pass

        def explore(self, rel, content, instruction):
            return ExplorationResult(files={"services/payment.py": "class PaymentService: ..."})

    monkeypatch.setattr("core.agent.ContextExplorer", FakeExplorer)
    result = agent._explore_context("controller.py", "conteudo", "usa payment", provider=None)
    assert result == {"services/payment.py": "class PaymentService: ..."}


def test_explore_failure_degrades_to_empty_context(tmp_path, store, monkeypatch):
    agent = _agent(tmp_path, store, {"ollama": OllamaProvider(Settings().providers.ollama)})

    class FailingExplorer:
        def __init__(self, *a, **kw):
            pass

        def explore(self, rel, content, instruction):
            raise ProviderError("ollama indisponível")

    monkeypatch.setattr("core.agent.ContextExplorer", FailingExplorer)
    result = agent._explore_context("controller.py", "conteudo", "usa payment", provider=None)
    assert result == {}
