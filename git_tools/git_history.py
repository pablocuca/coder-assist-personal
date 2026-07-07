"""Commit assistido (seção 17): mensagem sugerida pela IA, editável, nunca automática.

Nunca push, nunca operações destrutivas. Tudo via subprocess sem shell=True.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.errors import GitError


def _git(root: Path, *args: str, check: bool = True) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as e:
        raise GitError("Binário `git` não encontrado no PATH.") from e
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {' '.join(args)} excedeu o timeout.") from e
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} falhou: {result.stderr.strip()}")
    return result.stdout


def is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def status_porcelain(root: Path) -> str:
    return _git(root, "status", "--porcelain")


def has_staged_changes(root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    return result.returncode == 1


def stage_all(root: Path) -> None:
    _git(root, "add", "-A")


def staged_diff(root: Path, max_chars: int = 40_000) -> str:
    diff = _git(root, "diff", "--cached")
    if len(diff) > max_chars:
        stat = _git(root, "diff", "--cached", "--stat")
        return diff[:max_chars] + f"\n[... diff truncado ...]\n\nResumo:\n{stat}"
    return diff


def commit(root: Path, message: str) -> str:
    """Cria o commit e retorna o hash. Chamado apenas após confirmação explícita."""
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD").strip()
