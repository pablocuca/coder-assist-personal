"""ContextExplorer — loop de tool calling do `edit --explore` (opt-in, só Ollama)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.context_explorer import ContextExplorer
from core.errors import ProviderError
from core.settings import ContextDiscoverySettings, IndexingSettings

SYSTEM_PROMPT = "Explore arquivos relacionados."


class FakeOllama:
    """Simula OllamaProvider.chat_with_tools: uma resposta por chamada, na ordem dada."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> dict:
        self.calls.append(messages)
        if not self.responses:
            raise ProviderError("sem mais respostas configuradas no fake")
        return self.responses.pop(0)


def _tool_call(name: str, arguments: dict, call_id: str = "1") -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": arguments}}],
    }


def _final(text: str = "pronto") -> dict:
    return {"role": "assistant", "content": text}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "controller.py").write_text(
        "from services.payment import PaymentService\n\nclass Controller: ...\n"
    )
    services = tmp_path / "services"
    services.mkdir()
    (services / "payment.py").write_text("class PaymentService:\n    def charge(self): ...\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lixo.py").write_text("não deveria aparecer\n")
    return tmp_path


def _explorer(root: Path, provider: FakeOllama, **cfg_overrides) -> ContextExplorer:
    cfg = ContextDiscoverySettings(**cfg_overrides)
    return ContextExplorer(provider, root, IndexingSettings(), cfg, SYSTEM_PROMPT)


def test_stops_when_model_returns_no_tool_calls(project):
    provider = FakeOllama([_final()])
    explorer = _explorer(project, provider)
    result = explorer.explore("controller.py", "conteúdo", "adiciona um endpoint")
    assert result.files == {}
    assert result.tool_calls_used == 0
    assert not result.truncated_budget


def test_read_file_populates_result_and_respects_path_guard(project):
    provider = FakeOllama(
        [
            _tool_call("read_file", {"path": "services/payment.py"}),
            _final(),
        ]
    )
    explorer = _explorer(project, provider)
    result = explorer.explore("controller.py", "conteúdo", "usa PaymentService")
    assert "services/payment.py" in result.files
    assert "PaymentService" in result.files["services/payment.py"]
    assert result.tool_calls_used == 1


def test_read_file_outside_root_is_denied_not_raised(project):
    provider = FakeOllama(
        [
            _tool_call("read_file", {"path": "../../etc/passwd"}),
            _final(),
        ]
    )
    explorer = _explorer(project, provider)
    result = explorer.explore("controller.py", "conteúdo", "tenta escapar")
    assert result.files == {}  # não populou — a tool call recebeu "Acesso negado"
    tool_message = provider.calls[-1][-1]
    assert tool_message["role"] == "tool"
    assert "Acesso negado" in tool_message["content"]


def test_list_files_respects_ignore_rules(project):
    provider = FakeOllama(
        [
            _tool_call("list_files", {"pattern": "**/*.py"}),
            _final(),
        ]
    )
    explorer = _explorer(project, provider)
    explorer.explore("controller.py", "conteúdo", "lista arquivos python")
    tool_output = provider.calls[-1][-1]["content"]
    assert "controller.py" in tool_output
    assert "services/payment.py" in tool_output
    assert "node_modules" not in tool_output  # extra_ignores padrão


def test_list_files_double_star_matches_top_level_files_too(project):
    """Regressão: fnmatch exige barra literal — '**/*.py' não batia em
    'controller.py' na raiz do projeto sem o tratamento de prefixo opcional."""
    provider = FakeOllama(
        [
            _tool_call("list_files", {"pattern": "**/*.py"}),
            _final(),
        ]
    )
    explorer = _explorer(project, provider)
    explorer.explore("controller.py", "conteúdo", "lista todos os .py")
    tool_output = provider.calls[-1][-1]["content"]
    assert "controller.py" in tool_output


def test_grep_finds_occurrence_with_file_and_line(project):
    provider = FakeOllama(
        [
            _tool_call("grep", {"pattern": "PaymentService"}),
            _final(),
        ]
    )
    explorer = _explorer(project, provider)
    explorer.explore("controller.py", "conteúdo", "acha PaymentService")
    tool_output = provider.calls[-1][-1]["content"]
    assert "controller.py:1:" in tool_output


def test_tool_call_budget_stops_the_loop(project):
    # Sempre pede mais uma leitura — sem o orçamento, giraria para sempre.
    responses = [_tool_call("read_file", {"path": "controller.py"}) for _ in range(20)]
    provider = FakeOllama(responses)
    explorer = _explorer(project, provider, max_tool_calls=3)
    result = explorer.explore("controller.py", "conteúdo", "explora sem parar")
    assert result.tool_calls_used <= 3
    assert result.truncated_budget


def test_provider_error_mid_loop_returns_partial_result(project):
    provider = FakeOllama([_tool_call("read_file", {"path": "services/payment.py"})])
    # segunda chamada não tem resposta configurada -> ProviderError no fake
    explorer = _explorer(project, provider)
    result = explorer.explore("controller.py", "conteúdo", "algo")
    assert "services/payment.py" in result.files  # o que já foi lido não se perde


def test_max_files_caps_included_context(project):
    (project / "a.py").write_text("A\n")
    (project / "b.py").write_text("B\n")
    (project / "c.py").write_text("C\n")
    provider = FakeOllama(
        [
            _tool_call("read_file", {"path": "a.py"}),
            _tool_call("read_file", {"path": "b.py"}),
            _tool_call("read_file", {"path": "c.py"}),
            _final(),
        ]
    )
    explorer = _explorer(project, provider, max_files=2, max_tool_calls=10)
    result = explorer.explore("controller.py", "conteúdo", "lê tudo")
    assert len(result.files) == 2


def test_arguments_as_json_string_are_parsed(project):
    """Alguns runtimes de tool-calling devolvem 'arguments' como string JSON."""
    call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "1", "function": {"name": "read_file", "arguments": '{"path": "controller.py"}'}}
        ],
    }
    provider = FakeOllama([call, _final()])
    explorer = _explorer(project, provider)
    result = explorer.explore("controller.py", "conteúdo", "lê o alvo de novo")
    assert "controller.py" in result.files
