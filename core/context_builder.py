"""Montagem do contexto enviado ao modelo.

MVP: arquivo alvo + instrução, com truncamento defensivo para não estourar
a janela de modelos locais. Recall vetorial/FTS5 e histórico entram na V1.
"""

from __future__ import annotations

# Orçamento aproximado de caracteres para o conteúdo do arquivo
# (~15k tokens; modelos locais têm janelas modestas)
MAX_FILE_CHARS = 60_000


def _truncate_middle(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    half = max_chars // 2
    return (
        content[:half]
        + "\n\n[... TRECHO OMITIDO POR LIMITE DE CONTEXTO ...]\n\n"
        + content[-half:]
    )


def build_edit_prompt(rel_path: str, content: str, instruction: str, is_new: bool) -> str:
    if is_new:
        file_section = f"O arquivo `{rel_path}` ainda não existe e será criado agora."
    else:
        body = _truncate_middle(content, MAX_FILE_CHARS)
        file_section = f"Conteúdo atual do arquivo `{rel_path}`:\n```\n{body}\n```"
    return (
        f"{file_section}\n\n"
        f"Instrução do usuário: {instruction}\n\n"
        "Responda apenas com o JSON no formato EditProposal especificado."
    )


def build_ask_prompt(question: str, project_name: str) -> str:
    return f"Projeto atual: {project_name}\n\nPergunta: {question}"
