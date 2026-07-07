"""MemoryManager — indexação (seção 13) e registro de interações no vetorial.

- `aider index .`: incremental por padrão (invalidação por hash — seção 12),
  respeitando .gitignore real (pathspec) + extra_ignores, pulando binários.
- Interações: embedadas em best-effort após cada edit/ask; falha degrada com
  aviso, nunca bloqueia a edição (seção 19).
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import pathspec

from core.errors import ProviderError, VectorStoreError
from core.settings import Settings
from memory.chunker import chunk_code, chunk_conversation
from memory.embeddings import Embedder
from memory.sqlite_store import SQLiteStore
from memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

_BINARY_SNIFF_BYTES = 8192


@dataclass
class IndexReport:
    indexed_files: int = 0
    chunks: int = 0
    skipped: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(_BINARY_SNIFF_BYTES)
    except OSError:
        return True


def _load_gitignore(root: Path) -> pathspec.PathSpec | None:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return None
    lines = gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
    try:
        return pathspec.PathSpec.from_lines("gitignore", lines)
    except KeyError:  # pathspec antigo, sem a factory 'gitignore'
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)


class MemoryManager:
    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        project_root: Path,
        project_id: int,
        project_name: str,
    ):
        self.settings = settings
        self.store = store
        self.root = project_root
        self.project_id = project_id
        self.project_name = project_name
        self.embedder = Embedder(
            settings.embeddings,
            settings.providers.ollama.base_url,
            settings.providers.ollama.timeout_seconds,
        )
        self._vectors: VectorStore | None = None

    @property
    def vectors(self) -> VectorStore:
        if self._vectors is None:
            self._vectors = VectorStore(self.settings.state_dir, self.project_name)
        return self._vectors

    # --- varredura de arquivos (seção 13) --------------------------------------

    def _iter_candidate_files(self) -> Iterator[Path]:
        cfg = self.settings.indexing
        gitignore = _load_gitignore(self.root) if cfg.respect_gitignore else None
        extra_dirs = {i.rstrip("/") for i in cfg.extra_ignores if i.endswith("/")}
        extra_files = [i for i in cfg.extra_ignores if not i.endswith("/")]

        def walk(directory: Path) -> Iterator[Path]:
            for entry in sorted(directory.iterdir()):
                rel = entry.relative_to(self.root).as_posix()
                if entry.is_dir():
                    if entry.name in extra_dirs or entry.is_symlink():
                        continue
                    if gitignore and gitignore.match_file(rel + "/"):
                        continue
                    yield from walk(entry)
                    continue
                if gitignore and gitignore.match_file(rel):
                    continue
                if any(fnmatch.fnmatch(rel, pat) for pat in extra_files):
                    continue
                if not any(fnmatch.fnmatch(entry.name, pat) for pat in cfg.include):
                    continue
                yield entry

        yield from walk(self.root)

    # --- indexação --------------------------------------------------------------

    def index_project(
        self,
        full: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> IndexReport:
        report = IndexReport()
        cfg = self.settings.indexing
        max_bytes = cfg.max_indexed_file_kb * 1024

        if full:
            self.store.clear_index_state(self.project_id)

        for path in self._iter_candidate_files():
            rel = path.relative_to(self.root).as_posix()
            if progress:
                progress(rel)
            try:
                if path.stat().st_size > max_bytes:
                    report.skipped += 1
                    continue
                if _is_binary(path):
                    report.skipped += 1
                    continue
                raw = path.read_bytes()
                file_hash = _sha256_bytes(raw)
                if not full and self.store.indexed_hash(self.project_id, rel) == file_hash:
                    report.unchanged += 1
                    continue
                content = raw.decode("utf-8", errors="replace")
                count = self._index_file(rel, content, file_hash)
                report.indexed_files += 1
                report.chunks += count
            except (ProviderError, VectorStoreError):
                raise  # sem embedder/vetorial não há indexação — erro claro pro usuário
            except OSError as e:
                report.errors.append(f"{rel}: {e}")
        return report

    def _index_file(self, rel: str, content: str, file_hash: str) -> int:
        cfg = self.settings.embeddings
        chunks = chunk_code(content, cfg.chunk_max_lines, cfg.chunk_overlap_lines)
        # Invalidação: remove chunks antigos do arquivo antes de inserir os novos
        self.vectors.delete_by_file(rel)
        if chunks:
            texts = [c.text for c in chunks]
            embeddings = self.embedder.embed(texts)
            ids = [f"code:{self.project_name}:{rel}:{c.start_line}" for c in chunks]
            metadatas = [
                {
                    "type": "code_chunk",
                    "project": self.project_name,
                    "file": rel,
                    "file_hash": file_hash,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "embedding_model": self.embedder.model,
                    "timestamp": _now_iso(),
                }
                for c in chunks
            ]
            self.vectors.upsert(ids, texts, embeddings, metadatas)
        self.store.mark_indexed(
            self.project_id, rel, file_hash, len(chunks), self.embedder.model
        )
        return len(chunks)

    # --- interações (passo 12 do fluxo de edição) --------------------------------

    def index_interaction(
        self,
        interaction_id: int,
        prompt: str,
        response: str,
        tags: list[str] | None = None,
    ) -> None:
        """Best-effort: falha vira warning no log, nunca quebra o fluxo de edição."""
        try:
            documents = chunk_conversation(prompt, response or "")
            embeddings = self.embedder.embed(documents)
            ids = [f"interaction:{interaction_id}:{i}" for i in range(len(documents))]
            metadatas = [
                {
                    "type": "interaction",
                    "project": self.project_name,
                    "interaction_id": interaction_id,
                    "embedding_model": self.embedder.model,
                    "tags": ",".join(tags or []),
                    "timestamp": _now_iso(),
                }
                for _ in documents
            ]
            self.vectors.upsert(ids, documents, embeddings, metadatas)
        except (ProviderError, VectorStoreError) as e:
            logger.warning("memória vetorial indisponível para interação #%s: %s", interaction_id, e)

    def index_decision(
        self, interaction_id: int, text: str, tags: list[str] | None = None
    ) -> None:
        """Memória arquitetural (V2): um documento por decisão — best-effort."""
        try:
            embeddings = self.embedder.embed([text])
            self.vectors.upsert(
                ids=[f"decision:{interaction_id}"],
                texts=[text],
                embeddings=embeddings,
                metadatas=[
                    {
                        "type": "decision",
                        "project": self.project_name,
                        "interaction_id": interaction_id,
                        "embedding_model": self.embedder.model,
                        "tags": ",".join(tags or []),
                        "timestamp": _now_iso(),
                    }
                ],
            )
        except (ProviderError, VectorStoreError) as e:
            logger.warning("memória vetorial indisponível para decisão #%s: %s", interaction_id, e)

    def vector_count(self) -> int:
        try:
            return self.vectors.count()
        except VectorStoreError:
            return 0


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
