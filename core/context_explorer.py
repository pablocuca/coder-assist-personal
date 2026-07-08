"""Exploração agêntica de contexto — `edit --explore` (opt-in).

Só ativa com o provider Ollama, nunca com Claude: dá ao modelo local
ferramentas de leitura (list_files/grep/read_file), confinadas à raiz do
projeto pelo path guard e às mesmas regras de ignore da indexação, para ele
mesmo decidir quais arquivos relacionados ao alvo (imports, tipos citados,
classes/métodos chamados) são relevantes antes da edição propriamente dita.

Nunca escreve; orçamento rígido de chamadas de ferramenta e de caracteres
lidos evita loop sem fim ou exploração do projeto inteiro. O resultado é só
contexto de leitura — a proposta de edição continua passando pelo fluxo
normal (diff, aprovação, backup), e qualquer edição em arquivo descoberto
aqui ainda é reconferida contra o conteúdo real do disco antes de aplicar.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.context_builder import MAX_FILE_CHARS, truncate_middle
from core.errors import PathGuardError, ProviderError
from core.fs_scan import is_binary, iter_project_files
from core.settings import ContextDiscoverySettings, IndexingSettings
from providers.ollama_provider import OllamaProvider
from security.path_guard import validate_path

logger = logging.getLogger(__name__)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "Lista arquivos do projeto cujo caminho relativo casa com um glob "
                "(ex.: '**/*.py', 'src/services/*.cs')."
            ),
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Busca um texto/regex no conteúdo dos arquivos do projeto. "
                "Retorna arquivo e linha de cada ocorrência."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "glob": {
                        "type": "string",
                        "description": "Filtro opcional de arquivos, ex.: '*.py'",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lê o conteúdo de um arquivo do projeto pelo caminho relativo.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]


@dataclass
class ExplorationResult:
    files: dict[str, str] = field(default_factory=dict)  # rel -> conteúdo (truncado)
    tool_calls_used: int = 0
    truncated_budget: bool = False


class ContextExplorer:
    """Loop de tool calling contra o Ollama, confinado à raiz do projeto."""

    def __init__(
        self,
        provider: OllamaProvider,
        root: Path,
        indexing_cfg: IndexingSettings,
        cfg: ContextDiscoverySettings,
        system_prompt: str,
    ):
        self.provider = provider
        self.root = root
        self.indexing_cfg = indexing_cfg
        self.cfg = cfg
        self.system_prompt = system_prompt

    def explore(self, target_rel: str, target_content: str, instruction: str) -> ExplorationResult:
        result = ExplorationResult()
        system = f"{self.system_prompt}\n\nOrçamento: no máximo {self.cfg.max_tool_calls} chamadas de ferramenta."
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Arquivo alvo: `{target_rel}`\n"
                    f"```\n{truncate_middle(target_content, MAX_FILE_CHARS)}\n```\n\n"
                    f"Tarefa: {instruction}"
                ),
            },
        ]

        total_chars = 0
        for _ in range(self.cfg.max_tool_calls):
            try:
                message = self.provider.chat_with_tools(messages, tools=_TOOLS)
            except ProviderError as e:
                logger.warning("exploração de contexto interrompida: %s", e)
                break

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                break
            messages.append(message)

            for call in tool_calls:
                if result.tool_calls_used >= self.cfg.max_tool_calls:
                    result.truncated_budget = True
                    break
                result.tool_calls_used += 1
                name, args = _parse_call(call)
                output = self._run_tool(name, args, result, total_chars)
                total_chars += len(output)
                messages.append({"role": "tool", "content": output, "name": name})

            if result.truncated_budget or total_chars >= self.cfg.max_total_chars:
                result.truncated_budget = True
                break
        else:
            result.truncated_budget = True

        return result

    def _run_tool(self, name: str, args: dict, result: ExplorationResult, chars_so_far: int) -> str:
        try:
            if name == "list_files":
                return self._list_files(str(args.get("pattern", "")))
            if name == "grep":
                return self._grep(str(args.get("pattern", "")), args.get("glob"))
            if name == "read_file":
                return self._read_file(str(args.get("path", "")), result, chars_so_far)
            return f"Ferramenta desconhecida: {name}"
        except PathGuardError as e:
            return f"Acesso negado: {e}"
        except OSError as e:
            return f"Erro ao acessar: {e}"

    def _list_files(self, pattern: str) -> str:
        if not pattern:
            return "pattern vazio"
        matches = []
        for p in iter_project_files(self.root, self.indexing_cfg, include_all=True):
            rel = p.relative_to(self.root).as_posix()
            if _glob_match(rel, pattern):
                matches.append(rel)
                if len(matches) >= self.cfg.max_list_results:
                    break
        return "\n".join(matches) if matches else "nenhum arquivo encontrado"

    def _grep(self, pattern: str, glob: str | None) -> str:
        if not pattern:
            return "pattern vazio"
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"regex inválida: {e}"

        hits = []
        for p in iter_project_files(self.root, self.indexing_cfg, include_all=True):
            rel = p.relative_to(self.root).as_posix()
            if glob and not _glob_match(rel, glob):
                continue
            if is_binary(p):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= self.cfg.max_grep_results:
                        return "\n".join(hits)
        return "\n".join(hits) if hits else "nenhuma ocorrência"

    def _read_file(self, rel_path: str, result: ExplorationResult, chars_so_far: int) -> str:
        if not rel_path:
            return "path vazio"
        path = validate_path(self.root, rel_path)  # PathGuardError se sair da raiz
        if not path.exists():
            return f"arquivo não encontrado: {rel_path}"
        if is_binary(path):
            return "arquivo binário — não pode ser lido"

        content = path.read_text(encoding="utf-8", errors="replace")
        budget_left = max(self.cfg.max_total_chars - chars_so_far, 0)
        content = truncate_middle(content, min(MAX_FILE_CHARS, budget_left) or MAX_FILE_CHARS)

        rel = path.relative_to(self.root).as_posix()
        if len(result.files) < self.cfg.max_files:
            result.files[rel] = content
        return content


def _glob_match(rel: str, pattern: str) -> bool:
    """fnmatch exige barra literal: '**/*.py' não casa 'controller.py' na
    raiz. Trata '**/' como prefixo opcional, como o modelo espera."""
    if fnmatch.fnmatch(rel, pattern):
        return True
    if pattern.startswith("**/"):
        return fnmatch.fnmatch(rel, pattern[3:])
    return False


def _parse_call(call: dict) -> tuple[str, dict]:
    fn = call.get("function") or {}
    name = str(fn.get("name", ""))
    args = fn.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return name, args if isinstance(args, dict) else {}
