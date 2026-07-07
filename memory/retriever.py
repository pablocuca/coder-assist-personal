"""Recall (seção 14) — V1: busca vetorial com fontes; FTS5 como degradação.

Busca híbrida com Reciprocal Rank Fusion e --synthesize entram na V2.
Toda resposta carrega proveniência (tipo, arquivo/interação, data) — nunca
resultado sem fonte.
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
