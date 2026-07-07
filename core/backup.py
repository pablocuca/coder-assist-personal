"""Backups e pilha de undo (seção 16).

Backups vivem no diretório de estado (~/.coder-assist-pessoal/backups/<projeto>/),
nunca dentro do repositório do usuário. Retenção configurável por arquivo.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path


def _sanitize(rel_path: str) -> str:
    return rel_path.replace(os.sep, "__").replace("/", "__")


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")


class BackupManager:
    def __init__(self, state_dir: Path, project_name: str, retention: int):
        self.project_name = project_name
        self.backup_dir = state_dir / "backups" / project_name
        self.stack_file = state_dir / "undo_stack.json"
        self.retention = retention

    # --- backups -------------------------------------------------------------

    def create(self, root: Path, target: Path) -> Path:
        """Copia o arquivo atual para o diretório de backups e aplica retenção."""
        rel = str(target.relative_to(root))
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        dest = self.backup_dir / f"{_sanitize(rel)}.{_timestamp()}.bak"
        shutil.copy2(target, dest)
        self._prune(rel)
        return dest

    def _prune(self, rel: str) -> None:
        backups = sorted(self.backup_dir.glob(f"{_sanitize(rel)}.*.bak"))
        for old in backups[: max(0, len(backups) - self.retention)]:
            old.unlink()

    def list_for(self, root: Path, target: Path) -> list[Path]:
        rel = str(target.relative_to(root))
        return sorted(self.backup_dir.glob(f"{_sanitize(rel)}.*.bak"), reverse=True)

    # --- pilha de undo ---------------------------------------------------------

    def _load_stack(self) -> list[dict]:
        if not self.stack_file.exists():
            return []
        try:
            return json.loads(self.stack_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save_stack(self, stack: list[dict]) -> None:
        self.stack_file.parent.mkdir(parents=True, exist_ok=True)
        self.stack_file.write_text(
            json.dumps(stack, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def push_undo(self, target: Path, backup: Path | None) -> None:
        """backup=None significa arquivo criado do zero (undo = remover)."""
        stack = self._load_stack()
        stack.append(
            {
                "project": self.project_name,
                "file": str(target),
                "backup": str(backup) if backup else None,
                "timestamp": _timestamp(),
            }
        )
        self._save_stack(stack[-200:])  # limite defensivo da pilha

    def peek_undo(self) -> dict | None:
        for entry in reversed(self._load_stack()):
            if entry.get("project") == self.project_name:
                return entry
        return None

    def pop_undo(self) -> None:
        stack = self._load_stack()
        for i in range(len(stack) - 1, -1, -1):
            if stack[i].get("project") == self.project_name:
                del stack[i]
                break
        self._save_stack(stack)

    def undo_entries(self) -> list[dict]:
        return [e for e in self._load_stack() if e.get("project") == self.project_name]
