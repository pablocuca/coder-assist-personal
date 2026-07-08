"""Fábrica de providers conforme o modo de operação (settings.mode).

- offline:   só Ollama. O provider Claude nem é registrado — nenhuma chamada
             externa é possível, nem por engano. É o modo para implantação
             corporativa sem aprovação de tráfego externo.
- provider:  Ollama + Claude via Claude Code CLI autenticado (`claude login`).
- corporate: Ollama + Claude apontando para o endpoint sancionado pela
             organização (Bedrock/Vertex/gateway), via env vars injetadas na
             chamada e modelo opcionalmente sobrescrito
             (providers.claude.corporate em settings.yaml).
"""

from __future__ import annotations

from core.settings import Settings
from providers.base_provider import BaseProvider
from providers.claude_cli_provider import ClaudeCliProvider
from providers.ollama_provider import OllamaProvider


def build_providers(settings: Settings) -> dict[str, BaseProvider]:
    providers: dict[str, BaseProvider] = {
        "ollama": OllamaProvider(settings.providers.ollama)
    }
    if settings.mode == "provider":
        providers["claude"] = ClaudeCliProvider(settings.providers.claude)
    elif settings.mode == "corporate":
        cfg = settings.providers.claude
        corporate = cfg.corporate
        if corporate.model:
            cfg = cfg.model_copy(update={"model": corporate.model})
        providers["claude"] = ClaudeCliProvider(cfg, extra_env=dict(corporate.env))
    return providers
