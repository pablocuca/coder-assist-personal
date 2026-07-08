"""Modos de operação (settings.mode): offline, provider e corporate."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.settings import Settings
from providers.factory import build_providers
from tests.test_claude_provider import HELP_TEXT, _provider


def test_default_mode_is_provider():
    assert Settings().mode == "provider"


def test_invalid_mode_rejected():
    with pytest.raises(ValidationError):
        Settings.model_validate({"mode": "hibrido"})


def test_offline_registers_only_ollama():
    providers = build_providers(Settings.model_validate({"mode": "offline"}))
    assert sorted(providers) == ["ollama"]


def test_provider_mode_registers_both():
    providers = build_providers(Settings.model_validate({"mode": "provider"}))
    assert sorted(providers) == ["claude", "ollama"]
    assert providers["claude"].extra_env == {}


def test_corporate_mode_injects_env_and_model():
    settings = Settings.model_validate(
        {
            "mode": "corporate",
            "providers": {
                "claude": {
                    "corporate": {
                        "model": "us.anthropic.claude-sonnet-4-6-v1:0",
                        "env": {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1"},
                    }
                }
            },
        }
    )
    providers = build_providers(settings)
    claude = providers["claude"]
    assert claude.model == "us.anthropic.claude-sonnet-4-6-v1:0"
    assert claude.extra_env == {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1"}
    # o modelo corporativo não vaza para a config global
    assert settings.providers.claude.model == "claude-sonnet-4-6"


def test_corporate_env_reaches_subprocess(tmp_path):
    """As env vars corporativas precisam chegar ao processo do binário."""
    script = tmp_path / "claude-fake"
    payload = {"result": "ok", "total_cost_usd": 0.01}
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"HELP = {HELP_TEXT!r}\n"
        "if '--help' in sys.argv:\n"
        "    print(HELP)\n"
        "    sys.exit(0)\n"
        "sys.stdin.read()\n"
        f"payload = {payload!r}\n"
        "payload['result'] = os.environ.get('CODER_ASSIST_TEST_ENDPOINT', 'sem-env')\n"
        "print(json.dumps(payload))\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    provider = _provider(script)
    provider.extra_env = {"CODER_ASSIST_TEST_ENDPOINT": "bedrock-us-east-1"}
    response = provider.complete("prompt")
    assert response.text == "bedrock-us-east-1"
