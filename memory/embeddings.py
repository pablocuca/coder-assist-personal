"""Embeddings via Ollama (`nomic-embed-text`) — local, sem custo (seção 12).

Fallback opcional: sentence-transformers/all-MiniLM-L6-v2, usado apenas se o
pacote estiver instalado (`pip install sentence-transformers`) e o Ollama não
responder. O nome do modelo acompanha cada vetor nos metadados — se o modelo
mudar, é preciso re-indexar (`coder-dev index . --full`).
"""

from __future__ import annotations

import logging

import requests

from core.errors import ProviderError
from core.settings import EmbeddingsSettings

logger = logging.getLogger(__name__)

FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder:
    """Cliente de embeddings com fallback local opcional."""

    def __init__(self, cfg: EmbeddingsSettings, ollama_base_url: str, timeout_seconds: int = 120):
        self.cfg = cfg
        self.base_url = ollama_base_url.rstrip("/")
        self.timeout = timeout_seconds
        self.model = cfg.model
        self._fallback = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            return self._embed_ollama(texts)
        except ProviderError as e:
            fallback = self._load_fallback()
            if fallback is None:
                raise ProviderError(
                    f"{e}\nFallback local indisponível — instale com: "
                    "pip install sentence-transformers"
                ) from e
            logger.warning("embeddings: usando fallback %s (%s)", FALLBACK_MODEL, e)
            self.model = FALLBACK_MODEL
            return [vec.tolist() for vec in fallback.encode(texts)]

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        try:
            response = requests.post(
                f"{self.base_url}/api/embed",
                json={"model": self.cfg.model, "input": texts},
                timeout=self.timeout,
            )
            if response.status_code == 404:
                raise ProviderError(
                    f"Modelo de embedding '{self.cfg.model}' não instalado no Ollama. "
                    f"Rode: ollama pull {self.cfg.model}"
                )
            response.raise_for_status()
            data = response.json()
            embeddings = data.get("embeddings")
            if not embeddings or len(embeddings) != len(texts):
                raise ProviderError(f"Resposta de embedding inesperada do Ollama: {data.keys()}")
            return embeddings
        except ProviderError:
            raise
        except requests.RequestException as e:
            raise ProviderError(
                f"Ollama não respondeu em {self.base_url} para embeddings. Está rodando? — {e}"
            ) from e

    def _load_fallback(self):
        if self._fallback is not None:
            return self._fallback
        try:
            from sentence_transformers import SentenceTransformer  # opcional
        except ImportError:
            return None
        self._fallback = SentenceTransformer(FALLBACK_MODEL)
        return self._fallback
