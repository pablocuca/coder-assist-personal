"""Modelos pydantic do domínio e parsing de respostas da IA (seção 8).

O formato obrigatório de resposta é search/replace; `replace_file` só é
permitido para arquivos novos ou com menos de 100 linhas (validado no
patch engine, que conhece o arquivo alvo).
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError, model_validator

from core.errors import ParseError


class SearchReplaceEdit(BaseModel):
    file: str
    search: str | None = None
    replace: str | None = None
    replace_file: str | None = None  # conteúdo completo — arquivos novos ou < 100 linhas

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> "SearchReplaceEdit":
        has_sr = self.search is not None and self.replace is not None
        has_full = self.replace_file is not None
        if has_full and (self.search is not None or self.replace is not None):
            raise ValueError("edit não pode combinar search/replace com replace_file")
        if not has_sr and not has_full:
            raise ValueError("edit precisa de search+replace ou de replace_file")
        if has_sr and not self.search:
            raise ValueError("bloco search não pode ser vazio")
        return self


class EditProposal(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    edits: list[SearchReplaceEdit] = Field(min_length=1)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _candidates(text: str):
    """Gera candidatos a JSON: texto cru, blocos em fence, e o maior trecho {…}."""
    yield text.strip()
    for match in _FENCE_RE.finditer(text):
        yield match.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        yield text[start : end + 1]


def parse_edit_proposal(text: str) -> EditProposal:
    """Parseia e valida a resposta do modelo contra o schema EditProposal.

    Levanta ParseError se nenhum candidato for JSON válido conforme o schema —
    a re-tentativa guiada (uma única) é responsabilidade do Agent.
    """
    last_error: Exception | None = None
    for candidate in _candidates(text or ""):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as e:
            last_error = e
            continue
        try:
            return EditProposal.model_validate(data)
        except ValidationError as e:
            last_error = e
            continue
    raise ParseError(f"Resposta do modelo não é um EditProposal válido: {last_error}")
