"""Provider Claude via Claude Code CLI (`claude -p`) — wrapper de subprocess (seção 10).

Regras críticas implementadas aqui:
1. `subprocess.run` sem shell=True; prompt via STDIN (nunca argumento).
2. Comportamento agêntico neutralizado: nenhuma ferramenta pré-aprovada,
   `--max-turns 1`, cwd em diretório neutro/vazio — todo o contexto vai no prompt.
3. Autenticação é do próprio Claude Code (`claude login`); esta ferramenta
   nunca manipula API keys e NÃO usa `--bare`.
4. `--output-format json`: `result` é a resposta; `total_cost_usd` é o custo
   REAL registrado no banco. stderr é log, nunca controle de fluxo.
5. Flags exigidas são validadas contra `claude --help` na primeira execução.
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

REQUIRED_FLAGS = ("--model", "--output-format", "--max-turns", "--max-budget-usd")

_AUTH_HINTS = ("login", "logged in", "authenticate", "unauthorized", "api key", "oauth")
_LIMIT_HINTS = ("budget", "max turns", "max-turns", "limit")


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
        """As flags do Claude Code evoluem rápido — valida contra --help uma vez."""
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
        missing = [flag for flag in REQUIRED_FLAGS if flag not in help_text]
        if missing:
            raise ProviderError(
                f"A versão instalada do Claude Code não suporta as flags {missing}. "
                "Atualize com: npm update -g @anthropic-ai/claude-code"
            )
        self._flags_validated = True

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
        ]

        # cwd neutro: impede o agente de ler/editar o projeto por conta própria
        neutral_dir = tempfile.mkdtemp(prefix="aider-claude-neutral-")
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

        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        if stderr:
            logger.debug("claude stderr: %s", stderr)  # log de progresso, nunca parseado

        if result.returncode != 0:
            raise ProviderError(self._describe_failure(result.returncode, stderr))

        return self._parse_output(result.stdout.decode("utf-8", errors="replace"))

    def _describe_failure(self, returncode: int, stderr: str) -> str:
        lowered = stderr.lower()
        if any(hint in lowered for hint in _AUTH_HINTS):
            return (
                "Claude Code não está autenticado. Rode `claude login` "
                f"(exit {returncode}): {stderr[:300]}"
            )
        if any(hint in lowered for hint in _LIMIT_HINTS):
            return (
                f"Chamada interrompida por limite (--max-budget-usd "
                f"{self.cfg.max_budget_usd} / --max-turns {self.cfg.max_turns}). "
                f"Ajuste em settings.yaml e repita (exit {returncode}): {stderr[:300]}"
            )
        return f"Claude Code falhou (exit {returncode}): {stderr[:500]}"

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
