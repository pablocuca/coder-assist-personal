"""Redação de segredos — princípio 4.

A ferramenta não gerencia credenciais, mas segredos podem aparecer no
conteúdo de arquivos enviados como contexto. Tudo que vai para log ou
banco passa por aqui antes de persistir.
"""

from __future__ import annotations

import re

# Ordem importa: padrões mais específicos primeiro (sk-ant- antes de sk-).
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "anthropic-key"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "api-key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws-access-key"),
    (re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*\S+"), "aws-secret"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "github-token"),
    (re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"), "slack-token"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"), "jwt"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.=]{16,}"), "bearer-token"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|secret|password|senha)\b"
            r"\s*[=:]\s*['\"]?[^\s'\"]{8,}['\"]?"
        ),
        "credential-assignment",
    ),
]


def redact(text: str | None) -> str | None:
    """Substitui padrões de segredo por marcadores [REDACTED:<tipo>]."""
    if not text:
        return text
    for pattern, label in _PATTERNS:
        text = pattern.sub(f"[REDACTED:{label}]", text)
    return text
