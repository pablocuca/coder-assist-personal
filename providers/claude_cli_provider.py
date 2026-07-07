"""Provider Claude via Claude Code CLI (`claude -p`) — wrapper de subprocess (seção 10).

Regras críticas implementadas aqui:
1. `subprocess.run` sem shell=True; prompt via STDIN (nunca argumento).
2. Comportamento agêntico neutralizado em três camadas: instrução de
   somente-texto no system prompt (--append-system-prompt — o modelo obedece
   e responde em 1 turno), negação local de todas as ferramentas
   (--disallowed-tools com lista explícita — backup se tentar mesmo assim) e
   cwd em diretório neutro/vazio. IMPORTANTE: as ferramentas precisam
   continuar presentes na requisição à API — gateways corporativos (DLP)
   bloqueiam requisições do Claude Code sem o array de ferramentas padrão,
   o que descarta `--tools ""`, `--tools <nome-falso>` e
   `--disallowed-tools "*"` (todas removem o array e foram bloqueadas em
   ambiente corporativo real). A instrução precisa estar no SYSTEM prompt:
   na mensagem do usuário o modelo a ignora e insiste nas ferramentas
   anunciadas, estourando o max-turns.
3. Autenticação é do próprio Claude Code (`claude login`); esta ferramenta
   nunca manipula API keys e NÃO usa `--bare`.
4. `--output-format json`: `result` é a resposta; `total_cost_usd` é o custo
   REAL registrado no banco. stderr é log, nunca controle de fluxo.
5. Flags exigidas são validadas na primeira execução: contra `claude --help` e,
   para as ausentes do help (ex.: --max-turns na 2.x), sondando o parser do CLI.
6. Sem estado entre chamadas (one-shot); `--resume` fica para conversas na V2+.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile

from core.errors import ProviderError
from core.settings import ClaudeSettings
from providers.base_provider import BaseProvider, ProviderResponse

logger = logging.getLogger(__name__)

REQUIRED_FLAGS = (
    "--model",
    "--output-format",
    "--max-turns",
    "--max-budget-usd",
    "--disallowed-tools",
    "--append-system-prompt",
)

# Lista explícita (curinga "*" dispara DLP): nega localmente cada ferramenta
# nativa. Ferramentas novas de versões futuras ficam de fora da lista, mas a
# instrução de system prompt cobre; se ainda assim uma escapar, o sintoma é o
# error_max_turns visível, nunca execução silenciosa fora do diretório neutro.
_DISALLOWED_TOOLS = (
    "Task,Bash,Glob,Grep,Read,Edit,Write,NotebookEdit,WebFetch,WebSearch,"
    "TodoWrite,SlashCommand,Skill,KillShell,BashOutput,ExitPlanMode,AskUserQuestion"
)

_AUTH_HINTS = ("login", "logged in", "authenticate", "unauthorized", "api key", "oauth")
_LIMIT_HINTS = ("budget", "max turns", "max-turns", "max_turns", "limit")

# Vai no SYSTEM prompt (--append-system-prompt): na mensagem do usuário o
# modelo ignora o aviso e insiste nas ferramentas anunciadas na requisição.
_NO_TOOLS_NOTE = (
    "Nesta sessão todas as ferramentas estão desabilitadas por política — "
    "qualquer chamada de ferramenta falhará. Não tente usar ferramentas. "
    "Responda diretamente em texto, usando apenas o contexto fornecido na "
    "mensagem; se faltar informação, diga o que falta."
)


class ClaudeCliProvider(BaseProvider):
    name = "claude"

    def __init__(self, cfg: ClaudeSettings):
        self.cfg = cfg
        self.model = cfg.model
        self._flags_validated = False

    # --- pré-condições ----------------------------------------------------------

    def _ensure_binary(self) -> None:
        if shutil.which(self.cfg.binary) is None:
            raise ProviderError(
                f"Binário '{self.cfg.binary}' não encontrado no PATH. "
                "Instale com: npm i -g @anthropic-ai/claude-code (e rode `claude login`)."
            )

    def _validate_flags(self) -> None:
        """As flags do Claude Code evoluem rápido — valida uma vez, na primeira chamada."""
        if self._flags_validated:
            return
        try:
            result = subprocess.run(
                [self.cfg.binary, "--help"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ProviderError(f"Não foi possível executar `{self.cfg.binary} --help`: {e}") from e
        help_text = result.stdout + result.stderr
        # Flags podem sair do --help sem deixar de existir (o Claude Code 2.x
        # não lista mais --max-turns, mas continua aceitando). Ausência no
        # help é só suspeita — confirma sondando o parser do CLI.
        missing = [
            flag
            for flag in REQUIRED_FLAGS
            if flag not in help_text and self._flag_unknown(flag)
        ]
        if missing:
            raise ProviderError(
                f"A versão instalada do Claude Code não suporta as flags {missing}. "
                "Atualize com: npm update -g @anthropic-ai/claude-code"
            )
        self._flags_validated = True

    def _flag_unknown(self, flag: str) -> bool:
        """Sonda o parser: `claude <flag>` sem valor responde "unknown option"
        para flag inexistente e "argument missing" para flag conhecida.
        Na dúvida (falha da sonda), considera suportada — se não for, a
        chamada real falha com o erro descritivo de _describe_failure."""
        try:
            result = subprocess.run(
                [self.cfg.binary, flag],
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return "unknown option" in (result.stdout + result.stderr).lower()

    # --- chamada ------------------------------------------------------------------

    def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> ProviderResponse:
        self._ensure_binary()
        self._validate_flags()

        full_prompt = f"{system}\n\n---\n\n{prompt}" if system else prompt
        command = [
            self.cfg.binary,
            "-p",
            "--model", self.cfg.model,
            "--output-format", "json",
            "--max-turns", str(self.cfg.max_turns),
            "--max-budget-usd", str(self.cfg.max_budget_usd),
            # Neutralização em camadas (ver docstring do módulo): o array de
            # ferramentas fica na requisição (exigência de gateways DLP), tudo
            # negado localmente e o system prompt instrui a não tentar.
            "--disallowed-tools", _DISALLOWED_TOOLS,
            "--append-system-prompt", _NO_TOOLS_NOTE,
        ]

        # cwd neutro: impede o agente de ler/editar o projeto por conta própria
        neutral_dir = tempfile.mkdtemp(prefix="coder-assist-claude-neutral-")
        try:
            result = subprocess.run(
                command,
                input=full_prompt.encode("utf-8"),
                capture_output=True,
                timeout=self.cfg.timeout_seconds,
                cwd=neutral_dir,
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderError(
                f"Claude Code excedeu o timeout de {self.cfg.timeout_seconds}s."
            ) from e
        except OSError as e:
            raise ProviderError(f"Falha ao executar '{self.cfg.binary}': {e}") from e
        finally:
            shutil.rmtree(neutral_dir, ignore_errors=True)

        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        if stderr:
            logger.debug("claude stderr: %s", stderr)  # log de progresso, nunca parseado

        if result.returncode != 0:
            raise ProviderError(self._describe_failure(result.returncode, stderr, stdout))

        return self._parse_output(stdout)

    def _describe_failure(self, returncode: int, stderr: str, stdout: str = "") -> str:
        # Com --output-format json, o Claude Code reporta erros no STDOUT
        # (JSON com is_error/result) e pode sair com stderr vazio — a causa
        # precisa ser procurada nos dois.
        detail = stderr or self._error_from_stdout(stdout)
        lowered = f"{stderr}\n{stdout}".lower()
        if any(hint in lowered for hint in _AUTH_HINTS):
            return (
                "Claude Code não está autenticado. Rode `claude login` "
                f"(exit {returncode}): {detail[:300]}"
            )
        if any(hint in lowered for hint in _LIMIT_HINTS):
            return (
                f"Chamada interrompida por limite (--max-budget-usd "
                f"{self.cfg.max_budget_usd} / --max-turns {self.cfg.max_turns}). "
                f"Ajuste em settings.yaml e repita (exit {returncode}): {detail[:300]}"
            )
        if not detail:
            return (
                f"Claude Code falhou (exit {returncode}) sem mensagem no stdout/stderr. "
                "Diagnostique direto no terminal: echo teste | claude -p "
                f"--model {self.cfg.model} --output-format json"
            )
        return f"Claude Code falhou (exit {returncode}): {detail[:500]}"

    @staticmethod
    def _error_from_stdout(stdout: str) -> str:
        """Extrai a mensagem de erro do output JSON; texto cru como fallback."""
        text = stdout.strip()
        if not text:
            return ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(data, dict):
            for key in ("result", "error", "message"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return text

    def _parse_output(self, stdout: str) -> ProviderResponse:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"Output do Claude Code não é JSON válido: {e} — início: {stdout[:200]!r}"
            ) from e
        text = data.get("result")
        if text is None:
            raise ProviderError(
                f"Output JSON do Claude Code sem campo 'result'. Campos: {sorted(data)}"
            )
        if data.get("is_error"):
            raise ProviderError(f"Claude Code reportou erro: {str(text)[:500]}")
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=text,
            model=data.get("model", self.cfg.model),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            # custo REAL da chamada — é este valor que vai para o banco
            cost_usd=float(data.get("total_cost_usd") or 0.0),
        )
