"""Contrato comum dos providers. Nenhum código fora do Router deve chamá-los."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProviderResponse:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float = 0.0


class BaseProvider(ABC):
    name: str = "base"
    model: str = "?"

    @abstractmethod
    def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> ProviderResponse:
        """Envia um prompt e retorna a resposta completa (sem streaming no MVP)."""
        raise NotImplementedError
