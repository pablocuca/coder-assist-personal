"""Provider Claude via Claude Code CLI (`claude -p`) — implementação completa na V2.

No MVP este provider existe apenas para que a opção [e]scalar e
`--provider claude` falhem com uma mensagem clara em vez de crash
(seção 19). A implementação V2 seguirá a seção 10: subprocess sem
shell=True, prompt via stdin, cwd neutro, sem ferramentas, --max-turns 1,
--max-budget-usd, parse do JSON de saída com custo real.
"""

from __future__ import annotations

import shutil

from core.errors import ProviderError
from core.settings import ClaudeSettings
from providers.base_provider import BaseProvider, ProviderResponse


class ClaudeCliProvider(BaseProvider):
    name = "claude"

    def __init__(self, cfg: ClaudeSettings):
        self.cfg = cfg
        self.model = cfg.model

    def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> ProviderResponse:
        if shutil.which(self.cfg.binary) is None:
            raise ProviderError(
                f"Binário '{self.cfg.binary}' não encontrado no PATH. "
                "Instale com: npm i -g @anthropic-ai/claude-code (e rode `claude login`)."
            )
        raise ProviderError(
            "O provider Claude será implementado na V2 (wrapper headless sobre "
            "`claude -p`, seção 10 da especificação). Use --provider ollama por enquanto."
        )
