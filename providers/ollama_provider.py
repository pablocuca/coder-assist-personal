"""Provider Ollama local — padrão, offline-first, custo zero."""

from __future__ import annotations

import time

import requests

from core.errors import ProviderError
from core.settings import OllamaSettings
from providers.base_provider import BaseProvider, ProviderResponse


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, cfg: OllamaSettings):
        self.cfg = cfg
        self.model = cfg.model

    def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> ProviderResponse:
        url = self.cfg.base_url.rstrip("/") + "/api/chat"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict = {"model": self.model, "messages": messages, "stream": False}
        if json_mode:
            payload["format"] = "json"

        attempts = self.cfg.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = requests.post(url, json=payload, timeout=self.cfg.timeout_seconds)
                if response.status_code == 404:
                    raise ProviderError(
                        f"Ollama respondeu 404 para o modelo '{self.model}'. "
                        f"Ele está instalado? Tente: ollama pull {self.model}"
                    )
                response.raise_for_status()
                data = response.json()
                return ProviderResponse(
                    text=data["message"]["content"],
                    model=data.get("model", self.model),
                    input_tokens=data.get("prompt_eval_count"),
                    output_tokens=data.get("eval_count"),
                    cost_usd=0.0,
                )
            except ProviderError:
                raise
            except (KeyError, ValueError) as e:
                raise ProviderError(f"Resposta inesperada do Ollama: {e}") from e
            except requests.Timeout as e:
                last_error = e
            except requests.RequestException as e:
                last_error = e
            if attempt < attempts - 1:
                time.sleep(2**attempt)  # backoff exponencial: 1s, 2s, 4s…

        raise ProviderError(
            f"Ollama não respondeu em {self.cfg.base_url}. Está rodando? "
            f"(`ollama serve`) — último erro: {last_error}"
        )
