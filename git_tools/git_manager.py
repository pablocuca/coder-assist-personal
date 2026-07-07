"""Integração Git mínima do MVP: detecção de root, branch atual, working tree sujo.

Funciona normalmente sem Git — funções retornam None/False em vez de erro
(seção 17). Commit assistido e tabela `commits` entram na V1.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def find_project_root(start: Path) -> Path:
    """Raiz = diretório com .git subindo a partir de `start`; senão, o próprio start."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def _run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def current_branch(root: Path) -> str | None:
    return _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")


def is_file_dirty(root: Path, target: Path) -> bool:
    out = _run_git(root, "status", "--porcelain", "--", str(target))
    return bool(out)
