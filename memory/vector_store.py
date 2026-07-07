"""Banco vetorial ChromaDB — modo persistente local, uma coleção por projeto.

Import do chromadb é lazy: se estiver indisponível ou corrompido, quem chama
recebe VectorStoreError e degrada (edição funciona sem memória — seção 19).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from core.errors import VectorStoreError

logger = logging.getLogger(__name__)


def _collection_name(project_name: str) -> str:
    # Chroma exige [a-zA-Z0-9._-], 3-512 chars, começando com alfanumérico
    name = re.sub(r"[^a-zA-Z0-9._-]", "-", project_name).strip("._-") or "projeto"
    return (name if len(name) >= 3 else f"{name}-prj")[:512]


class VectorStore:
    def __init__(self, state_dir: Path, project_name: str):
        self.path = state_dir / "indexes" / project_name
        try:
            import chromadb

            self.path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.path))
            self._collection = self._client.get_or_create_collection(
                name=_collection_name(project_name),
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError as e:
            raise VectorStoreError(
                "chromadb não está instalado — memória vetorial indisponível. "
                "Instale com: pip install chromadb"
            ) from e
        except Exception as e:
            raise VectorStoreError(f"ChromaDB indisponível/corrompido em {self.path}: {e}") from e

    def upsert(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        if not ids:
            return
        try:
            self._collection.upsert(
                ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas
            )
        except Exception as e:
            raise VectorStoreError(f"Falha ao gravar vetores: {e}") from e

    def delete_by_file(self, rel_path: str) -> None:
        """Invalidação por hash: remove todos os chunks antigos de um arquivo."""
        try:
            self._collection.delete(where={"file": rel_path})
        except Exception as e:
            raise VectorStoreError(f"Falha ao invalidar chunks de {rel_path}: {e}") from e

    def query(
        self, embedding: list[float], k: int = 5, where: dict | None = None
    ) -> list[dict]:
        """Top-K por similaridade. Retorna [{id, text, metadata, distance}]."""
        try:
            result = self._collection.query(
                query_embeddings=[embedding],
                n_results=k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            raise VectorStoreError(f"Falha na busca vetorial: {e}") from e
        hits = []
        for i, item_id in enumerate(result["ids"][0]):
            hits.append(
                {
                    "id": item_id,
                    "text": result["documents"][0][i],
                    "metadata": result["metadatas"][0][i] or {},
                    "distance": result["distances"][0][i],
                }
            )
        return hits

    def count(self) -> int:
        try:
            return self._collection.count()
        except Exception as e:
            raise VectorStoreError(f"Falha ao contar vetores: {e}") from e
