"""Chunking (seção 12).

Código: janelas de até `chunk_max_lines` com overlap, quebrando de preferência
em fronteiras de função/classe (heurística por regex; tree-sitter é melhoria
opcional da V2). Conversas: um documento, dividido se exceder o limite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Fronteiras de função/classe nas linguagens indexadas por padrão
_BOUNDARY_RE = re.compile(
    r"^\s*(def |class |async def |function |const \w+ = |export |fun |void |"
    r"public |private |protected |static |Widget |@override|interface |struct |impl )"
)

# Limite defensivo por documento de conversa (~2k tokens do nomic-embed-text)
CONVERSATION_CHUNK_CHARS = 6_000


@dataclass
class Chunk:
    text: str
    start_line: int  # 1-based, inclusivo
    end_line: int


def chunk_code(content: str, max_lines: int = 80, overlap: int = 10) -> list[Chunk]:
    """Divide código em janelas com overlap, preferindo fronteiras de declaração.

    Estratégia: cada chunk vai até `max_lines`; se houver uma fronteira de
    função/classe na metade final da janela, quebra ali para não cortar
    declarações ao meio.
    """
    lines = content.splitlines()
    if not lines:
        return []
    if len(lines) <= max_lines:
        return [Chunk(text=content, start_line=1, end_line=len(lines))]

    chunks: list[Chunk] = []
    start = 0
    while start < len(lines):
        end = min(start + max_lines, len(lines))
        if end < len(lines):
            # procura fronteira na metade final da janela, de trás para frente
            for i in range(end - 1, start + max_lines // 2, -1):
                if _BOUNDARY_RE.match(lines[i]):
                    end = i
                    break
        chunks.append(
            Chunk(
                text="\n".join(lines[start:end]),
                start_line=start + 1,
                end_line=end,
            )
        )
        if end >= len(lines):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_conversation(prompt: str, response: str) -> list[str]:
    """Prompt + resposta como um documento; divide se exceder o limite."""
    document = f"{prompt}\n\n---\n\n{response}".strip()
    if len(document) <= CONVERSATION_CHUNK_CHARS:
        return [document]
    return [
        document[i : i + CONVERSATION_CHUNK_CHARS]
        for i in range(0, len(document), CONVERSATION_CHUNK_CHARS)
    ]
