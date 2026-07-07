"""Provider Claude com o binário `claude` mockado (seção 22 — critério da V2).

O fake é um script executável que simula o Claude Code: emite JSON no stdout,
exit codes de erro, demora (timeout) e valida que o prompt chegou via stdin
e que o cwd é um diretório neutro (não o projeto).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from core.errors import ProviderError
from core.settings import ClaudeSettings
from providers.claude_cli_provider import ClaudeCliProvider

HELP_TEXT = "Usage: claude [options]\n  --model  --output-format  --max-turns  --max-budget-usd"

SUCCESS_PAYLOAD = {
    "result": '{"confidence": 0.9, "explanation": "ok", "edits": []}',
    "session_id": "sess-123",
    "total_cost_usd": 0.0421,
    "usage": {"input_tokens": 900, "output_tokens": 120},
    "model": "claude-sonnet-4-6",
}


def _make_fake_claude(tmp_path: Path, body: str, help_text: str = HELP_TEXT) -> Path:
    """Cria um script python executável que simula o binário claude."""
    script = tmp_path / "claude-fake"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        f"HELP = {help_text!r}\n"
        "if '--help' in sys.argv:\n"
        "    print(HELP)\n"
        "    sys.exit(0)\n"
        + body
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _provider(binary: Path, **overrides) -> ClaudeCliProvider:
    cfg = ClaudeSettings(binary=str(binary), **overrides)
    return ClaudeCliProvider(cfg)


def test_success_parses_result_and_real_cost(tmp_path):
    marker = tmp_path / "invocacao.json"
    body = (
        "prompt = sys.stdin.read()\n"
        f"payload = {SUCCESS_PAYLOAD!r}\n"
        # registra como foi invocado, para as asserções
        f"open({str(marker)!r}, 'w').write(json.dumps("
        "{'prompt': prompt, 'argv': sys.argv[1:], 'cwd': os.getcwd()}))\n"
        "print(json.dumps(payload))\n"
    )
    provider = _provider(_make_fake_claude(tmp_path, body))
    response = provider.complete("edite o arquivo x", system="regras do sistema")

    assert '"confidence": 0.9' in response.text
    assert response.cost_usd == pytest.approx(0.0421)  # custo REAL do output JSON
    assert response.input_tokens == 900
    assert response.output_tokens == 120

    invocation = json.loads(marker.read_text())
    # prompt via stdin (nunca argumento), com o system embutido
    assert "edite o arquivo x" in invocation["prompt"]
    assert "regras do sistema" in invocation["prompt"]
    assert all("edite o arquivo" not in arg for arg in invocation["argv"])
    # flags obrigatórias da seção 10
    argv = invocation["argv"]
    assert "-p" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--max-turns" in argv and "1" in argv
    assert "--max-budget-usd" in argv
    # cwd neutro: nunca o diretório do projeto/teste
    assert invocation["cwd"] != os.getcwd()
    assert "coder-assist-claude-neutral-" in invocation["cwd"]


def test_missing_binary_clear_error(tmp_path):
    provider = _provider(tmp_path / "claude-que-nao-existe")
    with pytest.raises(ProviderError, match="não encontrado no PATH"):
        provider.complete("prompt")


def test_missing_required_flag_in_help(tmp_path):
    # O fake também rejeita a flag na sonda do parser, como um CLI que
    # realmente não a suporta.
    body = (
        "sys.stderr.write(\"error: unknown option '%s'\" % sys.argv[1])\n"
        "sys.exit(1)\n"
    )
    binary = _make_fake_claude(
        tmp_path, body, help_text="Usage: claude\n  --model  --output-format"
    )
    provider = _provider(binary)
    with pytest.raises(ProviderError, match="não suporta as flags"):
        provider.complete("prompt")


def test_flag_absent_from_help_but_accepted_by_parser(tmp_path):
    """Regressão: --max-turns sumiu do --help do Claude Code 2.x sem deixar
    de existir — a validação não pode dar falso negativo."""
    help_text = "Usage: claude\n  --model  --output-format  --max-budget-usd"
    body = (
        "if len(sys.argv) == 2:\n"  # sonda: `claude <flag>` sem valor
        "    sys.stderr.write(\"error: option '%s <n>' argument missing\" % sys.argv[1])\n"
        "    sys.exit(1)\n"
        f"print(json.dumps({SUCCESS_PAYLOAD!r}))\n"
    )
    provider = _provider(_make_fake_claude(tmp_path, body, help_text=help_text))
    response = provider.complete("prompt")
    assert response.cost_usd == pytest.approx(0.0421)


def test_auth_error_guides_login(tmp_path):
    body = "sys.stderr.write('Error: not logged in. Please run claude login.')\nsys.exit(1)\n"
    provider = _provider(_make_fake_claude(tmp_path, body))
    with pytest.raises(ProviderError, match="claude login"):
        provider.complete("prompt")


def test_budget_exceeded_reports_cause(tmp_path):
    body = "sys.stderr.write('Execution stopped: max budget exceeded')\nsys.exit(1)\n"
    provider = _provider(_make_fake_claude(tmp_path, body))
    with pytest.raises(ProviderError, match="limite"):
        provider.complete("prompt")


def test_error_only_on_stdout_json_is_surfaced(tmp_path):
    """Regressão: com --output-format json, o Claude Code reporta erros no
    STDOUT e pode sair com stderr vazio — a causa não pode ser engolida."""
    body = (
        'print(json.dumps({"type": "result", "is_error": True,'
        ' "result": "Credit balance is too low"}))\n'
        "sys.exit(1)\n"
    )
    provider = _provider(_make_fake_claude(tmp_path, body))
    with pytest.raises(ProviderError, match="Credit balance is too low"):
        provider.complete("prompt")


def test_auth_error_on_stdout_guides_login(tmp_path):
    body = (
        'print(json.dumps({"result": "OAuth token expired. Please run /login"}))\n'
        "sys.exit(1)\n"
    )
    provider = _provider(_make_fake_claude(tmp_path, body))
    with pytest.raises(ProviderError, match="claude login"):
        provider.complete("prompt")


def test_failure_with_no_output_suggests_terminal_diagnosis(tmp_path):
    body = "sys.exit(1)\n"
    provider = _provider(_make_fake_claude(tmp_path, body))
    with pytest.raises(ProviderError, match="sem mensagem no stdout/stderr"):
        provider.complete("prompt")


def test_timeout_raises_provider_error(tmp_path):
    body = "time.sleep(10)\nprint('{}')\n"
    provider = _provider(_make_fake_claude(tmp_path, body), timeout_seconds=1)
    with pytest.raises(ProviderError, match="timeout"):
        provider.complete("prompt")


def test_invalid_json_stdout(tmp_path):
    body = "print('isto não é json')\n"
    provider = _provider(_make_fake_claude(tmp_path, body))
    with pytest.raises(ProviderError, match="não é JSON válido"):
        provider.complete("prompt")


def test_is_error_payload(tmp_path):
    body = 'print(json.dumps({"result": "algo deu errado", "is_error": True}))\n'
    provider = _provider(_make_fake_claude(tmp_path, body))
    with pytest.raises(ProviderError, match="reportou erro"):
        provider.complete("prompt")


def test_stderr_never_breaks_success(tmp_path):
    """stderr é log de progresso — nunca controle de fluxo."""
    body = (
        "sys.stderr.write('progresso: pensando...')\n"
        f"print(json.dumps({SUCCESS_PAYLOAD!r}))\n"
    )
    provider = _provider(_make_fake_claude(tmp_path, body))
    response = provider.complete("prompt")
    assert response.cost_usd > 0
