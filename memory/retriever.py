"""Recall (seção 14) — busca híbrida: vetorial (ChromaDB) + keyword (FTS5),
fundidas por Reciprocal Rank Fusion; FTS5 sozinho como degradação.

Toda resposta carrega proveniência (tipo, arquivo/interação, data) — nunca
resultado sem fonte, com ou sem --synthesize.
"""

from __future__ import annotations

from dataclasses import dataclass

from memory.embeddings import Embedder
from memory.sqlite_store import SQLiteStore
from memory.vector_store import VectorStore


@dataclass
class RecallHit:
    score: float           # 0..1 (1 = mais relevante)
    type: str              # interaction | code_chunk | decision
    source: str            # "interação #12" | "src/app.py:10-80"
    timestamp: str
    snippet: str
    tags: list[str]


class Retriever:
    def __init__(self, vector_store: VectorStore | None, embedder: Embedder, store: SQLiteStore):
        self.vectors = vector_store
        self.embedder = embedder
        self.store = store

    def recall(self, query: str, k: int = 5) -> list[RecallHit]:
        embedding = self.embedder.embed([query])[0]
        hits = self.vectors.query(embedding, k=k)
        results = []
        for hit in hits:
            meta = hit["metadata"]
            kind = meta.get("type", "code_chunk")
            if kind == "interaction":
                source = f"interação #{meta.get('interaction_id', '?')}"
            elif kind == "decision":
                source = f"decisão #{meta.get('interaction_id', '?')}"
            else:
                lines = (
                    f":{meta['start_line']}-{meta['end_line']}"
                    if "start_line" in meta
                    else ""
                )
                source = f"{meta.get('file', '?')}{lines}"
            tags = [t for t in (meta.get("tags") or "").split(",") if t]
            results.append(
                RecallHit(
                    # distância cosseno ∈ [0, 2] → score ∈ [0, 1]
                    score=max(0.0, 1.0 - hit["distance"] / 2.0),
                    type=kind,
                    source=source,
                    timestamp=meta.get("timestamp", "?"),
                    snippet=hit["text"][:400],
                    tags=tags,
                )
            )
        return results

    def recall_hybrid(
        self, query: str, project: str | None = None, k: int = 5, rrf_k: int = 60
    ) -> list[RecallHit]:
        """Fusão RRF: score(d) = Σ 1/(rrf_k + rank_na_lista). Fontes deduplicadas."""
        vector_hits = self.recall(query, k=k * 2)
        keyword_hits = self.recall_keyword(query, project=project, k=k * 2)

        fused: dict[str, tuple[float, RecallHit]] = {}
        for hits in (vector_hits, keyword_hits):
            for rank, hit in enumerate(hits, start=1):
                score = 1.0 / (rrf_k + rank)
                if hit.source in fused:
                    old_score, best = fused[hit.source]
                    # mantém o snippet mais rico (vetorial vem primeiro e tem metadados)
                    fused[hit.source] = (old_score + score, best)
                else:
                    fused[hit.source] = (score, hit)

        ranked = sorted(fused.values(), key=lambda pair: pair[0], reverse=True)[:k]
        results = []
        for score, hit in ranked:
            hit.score = score  # score RRF substitui o score de origem
            results.append(hit)
        return results

    def build_synthesis_prompt(self, query: str, hits: list[RecallHit]) -> str:
        """Prompt de síntese com fontes numeradas — a resposta deve citar [n]."""
        sources = "\n\n".join(
            f"[{i}] ({hit.type} — {hit.source}, {hit.timestamp})\n{hit.snippet}"
            for i, hit in enumerate(hits, 1)
        )
        return (
            f"Pergunta: {query}\n\n"
            f"Fontes recuperadas do histórico e do código:\n\n{sources}\n\n"
            "Responda a pergunta usando apenas as fontes acima, citando-as como [1], [2]…"
        )

    def recall_keyword(self, query: str, project: str | None = None, k: int = 5) -> list[RecallHit]:
        """Degradação por FTS5 quando o vetorial está indisponível."""
        rows = self.store.fts_search(query, project=project, limit=k)
        return [
            RecallHit(
                score=0.0,
                type="interaction",
                source=f"interação #{row['id']}",
                timestamp=row["timestamp"],
                snippet=(row.get("response") or row["prompt"] or "")[:400],
                tags=[],
            )
            for row in rows
        ]
