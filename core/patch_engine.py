"""Aplicação de edits search/replace e escrita atômica (seções 8 e 9).

Regras:
- `search` deve casar exatamente uma vez; zero ou múltiplos matches → PatchError.
- Escrita: arquivo temporário no mesmo diretório + os.replace (atômico no
  mesmo filesystem). Ctrl+C ou falha no meio nunca deixa o arquivo corrompido.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from core.errors import PatchError

# replace_file só é permitido para arquivos novos ou menores que isto (seção 8, regra 2)
REPLACE_FILE_MAX_LINES = 100


def apply_search_replace(content: str, search: str, replace: str) -> str:
    """Aplica um bloco search/replace exigindo match único."""
    count = content.count(search)
    if count == 0:
        raise PatchError(
            "Bloco `search` não encontrado no arquivo:\n---\n" + search + "\n---"
        )
    if count > 1:
        raise PatchError(
            f"Bloco `search` ambíguo ({count} ocorrências) — adicione mais contexto:\n---\n"
            + search
            + "\n---"
        )
    return content.replace(search, replace, 1)


def check_replace_file_allowed(original: str, is_new_file: bool) -> None:
    """`replace_file` só para arquivos novos ou com menos de 100 linhas."""
    if is_new_file:
        return
    if len(original.splitlines()) >= REPLACE_FILE_MAX_LINES:
        raise PatchError(
            f"`replace_file` só é permitido para arquivos novos ou com menos de "
            f"{REPLACE_FILE_MAX_LINES} linhas. Use blocos search/replace."
        )


def atomic_write(path: Path, content: str) -> None:
    """Grava atomicamente: tmp no mesmo diretório + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
