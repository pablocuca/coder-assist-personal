"""Varredura de arquivos do projeto respeitando .gitignore + extra_ignores.

Compartilhado pela indexação (memory_manager) e pela exploração de contexto
do Agent (context_explorer) — a mesma política de "o que é do projeto" vale
para os dois, para não abrir uma segunda porta com regras diferentes.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterator

import pathspec

from core.settings import IndexingSettings

_BINARY_SNIFF_BYTES = 8192


def load_gitignore(root: Path) -> pathspec.PathSpec | None:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return None
    lines = gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
    try:
        return pathspec.PathSpec.from_lines("gitignore", lines)
    except KeyError:  # pathspec antigo, sem a factory 'gitignore'
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def is_binary(path: Path, sniff_bytes: int = _BINARY_SNIFF_BYTES) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(sniff_bytes)
    except OSError:
        return True


def iter_project_files(
    root: Path, cfg: IndexingSettings, include_all: bool = False
) -> Iterator[Path]:
    """Varre `root` respeitando .gitignore + extra_ignores.

    `include_all=True` ignora `cfg.include` — usado pela exploração de
    contexto, que precisa enxergar qualquer arquivo texto do projeto, não só
    as extensões elegíveis para indexação vetorial.
    """
    gitignore = load_gitignore(root) if cfg.respect_gitignore else None
    extra_dirs = {i.rstrip("/") for i in cfg.extra_ignores if i.endswith("/")}
    extra_files = [i for i in cfg.extra_ignores if not i.endswith("/")]

    def walk(directory: Path) -> Iterator[Path]:
        for entry in sorted(directory.iterdir()):
            rel = entry.relative_to(root).as_posix()
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
            if not include_all and not any(
                fnmatch.fnmatch(entry.name, pat) for pat in cfg.include
            ):
                continue
            yield entry

    yield from walk(root)
