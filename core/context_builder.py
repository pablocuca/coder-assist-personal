"""Montagem do contexto enviado ao modelo.

MVP: arquivo alvo + instrução, com truncamento defensivo para não estourar
a janela de modelos locais. Recall vetorial/FTS5 e histórico entram na V1.
"""

from __future__ import annotations

# Orçamento aproximado de caracteres para o conteúdo do arquivo
# (~15k tokens; modelos locais têm janelas modestas)
MAX_FILE_CHARS = 60_000


def truncate_middle(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    half = max_chars // 2
    return (
        content[:half]
        + "\n\n[... TRECHO OMITIDO POR LIMITE DE CONTEXTO ...]\n\n"
        + content[-half:]
    )


def build_edit_prompt(
    rel_path: str,
    content: str,
    instruction: str,
    is_new: bool,
    related: dict[str, str] | None = None,
) -> str:
    if is_new:
        file_section = f"O arquivo `{rel_path}` ainda não existe e será criado agora."
    else:
        body = truncate_middle(content, MAX_FILE_CHARS)
        file_section = (
            f"Conteúdo atual do arquivo `{rel_path}` (alvo principal — edite este):\n"
            f"```\n{body}\n```"
        )

    context_section = ""
    if related:
        blocks = "\n\n".join(
            f"Arquivo de referência `{rel}`:\n```\n{truncate_middle(text, MAX_FILE_CHARS)}\n```"
            for rel, text in related.items()
        )
        context_section = (
            "\n\nArquivos relacionados encontrados na exploração (contexto — só "
            f"proponha edições neles se a tarefa exigir; o alvo principal é `{rel_path}`):\n\n"
            f"{blocks}\n"
        )

    return (
        f"{file_section}{context_section}\n\n"
        f"Instrução do usuário: {instruction}\n\n"
        "Responda apenas com o JSON no formato EditProposal especificado."
    )


def build_ask_prompt(question: str, project_name: str) -> str:
    return f"Projeto atual: {project_name}\n\nPergunta: {question}"
