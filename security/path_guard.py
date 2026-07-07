"""Validação de paths — princípio 3: nenhuma escrita fora do root do projeto.

Paths são resolvidos (Path.resolve(), que segue symlinks) e validados
contra a raiz antes de qualquer operação de leitura ou escrita.
"""

from __future__ import annotations

from pathlib import Path

from core.errors import PathGuardError


def validate_path(root: Path | str, candidate: Path | str) -> Path:
    """Resolve `candidate` e garante que fica dentro de `root`.

    Rejeita traversal (`../`), paths absolutos externos e symlinks que
    apontem para fora do root. Retorna o Path absoluto resolvido.
    """
    root_resolved = Path(root).resolve()
    p = Path(candidate).expanduser()
    if not p.is_absolute():
        p = root_resolved / p
    resolved = p.resolve()

    if resolved == root_resolved:
        raise PathGuardError(
            f"O alvo deve ser um arquivo dentro do projeto, não a própria raiz: '{candidate}'"
        )
    if not resolved.is_relative_to(root_resolved):
        raise PathGuardError(
            f"Path fora do diretório do projeto: '{candidate}' resolve para "
            f"'{resolved}' (raiz do projeto: '{root_resolved}')"
        )
    return resolved
