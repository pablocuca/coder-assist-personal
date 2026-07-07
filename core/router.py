"""Router — middleware obrigatório (princípio 2 e seção 10).

Nenhuma chamada acessa modelos diretamente: tudo passa por Router.ask(),
que registra 100% das interações no SQLite (prompt redigido, resposta,
provider, modelo, duração, tokens, custo, branch, status).
"""

from __future__ import annotations

import logging
import time

from core.errors import ProviderError
from core.settings import Settings
from memory.sqlite_store import SQLiteStore
from providers.base_provider import BaseProvider, ProviderResponse
from security.redactor import redact

logger = logging.getLogger(__name__)


class Router:
    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        providers: dict[str, BaseProvider],
        *,
        project_id: int | None = None,
        git_branch: str | None = None,
    ):
        self.settings = settings
        self.store = store
        self.providers = providers
        self.project_id = project_id
        self.git_branch = git_branch

    def _redact(self, text: str | None) -> str | None:
        if text is None:
            return None
        return redact(text) if self.settings.logging.redact_secrets else text

    def ask(
        self,
        task_type: str,
        prompt: str,
        *,
        system: str | None = None,
        provider: str | None = None,
        json_mode: bool = False,
    ) -> tuple[int, ProviderResponse]:
        """Envia o prompt ao provider escolhido e registra a interação.

        Retorna (interaction_id, resposta). Em falha do provider, registra a
        interação com status `provider_error` e re-levanta a exceção.
        """
        name = provider or self.settings.providers.default
        if name not in self.providers:
            raise ProviderError(
                f"Provider desconhecido: '{name}'. Disponíveis: {sorted(self.providers)}"
            )
        chosen = self.providers[name]

        # O que persiste é sempre a versão redigida (princípio 4)
        stored_prompt = self._redact(
            f"[system]\n{system}\n\n[user]\n{prompt}" if system else prompt
        )

        start = time.monotonic()
        try:
            response = chosen.complete(prompt, system=system, json_mode=json_mode)
        except ProviderError as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            self.store.record_interaction(
                project_id=self.project_id,
                task_type=task_type,
                provider=name,
                model=chosen.model,
                prompt=stored_prompt,
                response=self._redact(str(e)),
                duration_ms=duration_ms,
                status="provider_error",
                git_branch=self.git_branch,
            )
            logger.error("provider_error [%s/%s]: %s", name, chosen.model, e)
            raise

        duration_ms = int((time.monotonic() - start) * 1000)
        interaction_id = self.store.record_interaction(
            project_id=self.project_id,
            task_type=task_type,
            provider=name,
            model=response.model,
            prompt=stored_prompt,
            response=self._redact(response.text),
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            duration_ms=duration_ms,
            cost_estimate=response.cost_usd,
            status="ok",
            git_branch=self.git_branch,
        )
        logger.info(
            "interaction #%s [%s/%s] %s: %sms",
            interaction_id, name, response.model, task_type, duration_ms,
        )
        return interaction_id, response

    def should_escalate(self, confidence: float | None) -> bool:
        """Política mínima do MVP: confidence é um sinal, não o único critério.

        A política completa (contexto excedido, falhas consecutivas de parse,
        task_type complexo) entra na V2.
        """
        if confidence is None:
            return True
        return confidence < self.settings.router.confidence_threshold
