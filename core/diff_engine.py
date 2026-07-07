"""Geração de diff unificado — sempre em memória, nunca toca o disco."""

from __future__ import annotations

import difflib


def unified_diff(original: str, updated: str, path: str) -> str:
    """Diff unificado entre o conteúdo original e o proposto.

    Retorna string vazia quando não há mudanças. Funciona para arquivo
    novo (original == "") e para esvaziamento de arquivo.
    """
    if original == updated:
        return ""
    a = original.splitlines()
    b = updated.splitlines()
    lines = difflib.unified_diff(
        a, b, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""
    )
    return "\n".join(lines)
