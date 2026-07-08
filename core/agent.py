"""Agent — orquestra o fluxo de edição (seção 9) e a política de escalada (V2).

proposta → diff por arquivo → aprovação explícita (individual ou em lote) →
re-verificação de hash → backup → gravação atômica → registro. A IA nunca
grava diretamente (princípio 1).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from cli.ui import UI
from core.backup import BackupManager
from core.context_builder import build_ask_prompt, build_edit_prompt
from core.context_explorer import ContextExplorer
from core.diff_engine import unified_diff
from core.errors import ParseError, PatchError, PathGuardError, ProviderError
from core.patch_engine import apply_search_replace, atomic_write, check_replace_file_allowed
from core.router import Router
from core.settings import Settings, load_prompt
from git_tools.git_manager import is_file_dirty
from memory.memory_manager import MemoryManager
from memory.sqlite_store import SQLiteStore
from models.schemas import EditProposal, parse_edit_proposal
from providers.ollama_provider import OllamaProvider
from security.path_guard import validate_path

logger = logging.getLogger(__name__)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class TargetFile:
    rel: str
    path: Path
    original: str
    original_hash: str
    is_new: bool
    updated: str | None = None  # preenchido após aplicar os edits


def apply_proposal(
    targets: dict[str, TargetFile], proposal: EditProposal
) -> tuple[list[str], list[tuple[str, PatchError]]]:
    """Aplica os edits em memória, por arquivo, na ordem da proposta.

    Retorna (arquivos alterados com sucesso, [(arquivo, erro)] dos que falharam).
    Função pura sobre os TargetFile — nada toca o disco aqui.
    """
    contents = {rel: t.original for rel, t in targets.items()}
    failed: dict[str, PatchError] = {}
    for edit in proposal.edits:
        rel = _normalize(edit.file)
        if rel in failed:
            continue  # arquivo já falhou; não aplica edits subsequentes nele
        target = targets[rel]
        try:
            if edit.replace_file is not None:
                check_replace_file_allowed(target.original, target.is_new)
                contents[rel] = edit.replace_file
            else:
                contents[rel] = apply_search_replace(contents[rel], edit.search, edit.replace)
        except PatchError as e:
            failed[rel] = e

    changed = []
    for rel, target in targets.items():
        if rel in failed:
            continue
        if contents[rel] != target.original:
            target.updated = contents[rel]
            changed.append(rel)
    return changed, list(failed.items())


def _normalize(file_str: str) -> str:
    return file_str.strip().lstrip("./")


class Agent:
    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        router: Router,
        ui: UI,
        project_root: Path,
        project_id: int,
        memory: MemoryManager | None = None,
    ):
        self.settings = settings
        self.store = store
        self.router = router
        self.ui = ui
        self.root = project_root
        self.project_id = project_id
        self.memory = memory
        self.backups = BackupManager(
            settings.state_dir, project_root.name, settings.editing.backup_retention
        )

    # --- edit -----------------------------------------------------------------

    def edit(
        self,
        file_arg: str,
        instruction: str,
        provider: str | None = None,
        plan: bool = False,
        explore: bool = False,
    ) -> None:
        # 1. Validar path e ler o arquivo principal
        path = validate_path(self.root, file_arg)
        rel = str(path.relative_to(self.root))
        is_new = not path.exists()
        original = "" if is_new else path.read_text(encoding="utf-8")

        if not is_new:
            size_kb = path.stat().st_size / 1024
            if size_kb > self.settings.editing.max_file_size_kb:
                if not self.ui.confirm(
                    f"O arquivo tem {size_kb:.0f} KB (limite: "
                    f"{self.settings.editing.max_file_size_kb} KB). Enviar mesmo assim?"
                ):
                    self.ui.info("Operação cancelada.")
                    return
            if is_file_dirty(self.root, path):
                self.ui.warn(
                    f"O working tree do Git está sujo em '{rel}' — o backup cobre o "
                    "rollback, mas considere commitar antes."
                )

        related: dict[str, str] = {}
        if explore and not is_new:
            related = self._explore_context(rel, original, instruction, provider)

        system = load_prompt("edit.md")
        user_prompt = build_edit_prompt(rel, original, instruction, is_new, related=related or None)

        # (V2) Planejamento: plano em passos exibido antes de editar
        if plan and not self._show_plan(rel, original, instruction, provider):
            return

        # Escalada de saída: pedida pelo usuário, ou contexto grande demais p/ local
        proceed, provider = self._resolve_initial_provider(provider, len(user_prompt))
        if not proceed:
            self.ui.info("Operação cancelada.")
            return

        # 2-6. Router → parse com re-tentativa guiada (e oferta de escalada)
        result = self._request_proposal(user_prompt, system, provider)
        if result is None:
            return
        proposal, interaction_id, provider = result
        self.store.update_interaction(interaction_id, confidence=proposal.confidence)

        # 7. Carregar alvos (multi-arquivo) e aplicar em memória — nunca no disco
        targets = self._load_targets(proposal, interaction_id)
        if targets is None:
            return
        changed, failed = apply_proposal(targets, proposal)
        if failed:
            for failed_rel, error in failed:
                self.ui.error(f"{failed_rel}: {error}")
            if not changed:
                self.store.update_interaction(interaction_id, status="rejected")
                self.ui.error("Nenhum edit pôde ser aplicado. Operação abortada.")
                return
            if not self.ui.confirm(
                f"Edits de {len(failed)} arquivo(s) falharam; {len(changed)} arquivo(s) "
                "aplicaram. Continuar apenas com os que aplicaram?"
            ):
                self.store.update_interaction(interaction_id, status="rejected")
                self.ui.info("Operação cancelada.")
                return
        if not changed:
            self.ui.info("A proposta não altera nenhum arquivo. Nada a fazer.")
            return

        # 8. Exibir explicação + um diff por arquivo
        self.ui.show_explanation(proposal.explanation, proposal.confidence, files=changed)
        diffs = {
            r: unified_diff(targets[r].original, targets[r].updated, r) for r in changed
        }
        for changed_rel, diff in diffs.items():
            self.ui.show_diff(diff, title=changed_rel)

        reasons = self.router.escalation_reasons(
            confidence=proposal.confidence, task_type="edit"
        )
        if provider != "claude" and reasons and self._claude_available():
            if self.settings.router.auto_escalate:
                self.ui.warn("Escalada automática: " + "; ".join(reasons))
                self.store.update_interaction(interaction_id, status="rejected")
                return self._escalate(file_arg, instruction, len(user_prompt))
            self.ui.warn("; ".join(reasons) + " — considere [e]scalar.")

        # 9. Aprovação: em lote ou individual (multi-arquivo)
        approved = self._approve(changed, provider)
        if approved == "escalate":
            self.store.update_interaction(interaction_id, status="rejected")
            return self._escalate(file_arg, instruction, len(user_prompt))
        if not approved:
            self.store.update_interaction(interaction_id, status="rejected")
            self.ui.info("Proposta rejeitada. Nenhum arquivo foi alterado.")
            return

        # 10. Gravar cada arquivo aprovado: re-hash → backup → escrita atômica
        written = []
        for approved_rel in approved:
            target = targets[approved_rel]
            current = target.path.read_text(encoding="utf-8") if target.path.exists() else ""
            if _sha256(current) != target.original_hash:
                self.ui.error(
                    f"'{approved_rel}' mudou no disco desde a leitura — pulado. "
                    "Repita o edit para este arquivo."
                )
                continue
            backup = None if target.is_new else self.backups.create(self.root, target.path)
            atomic_write(target.path, target.updated)
            self.backups.push_undo(target.path, backup)
            file_id = self.store.upsert_file(
                self.project_id, approved_rel, _sha256(target.updated)
            )
            self.store.link_interaction_file(interaction_id, file_id)
            written.append(approved_rel)
            note = f"backup: {backup.name}" if backup else "arquivo novo"
            self.ui.success(f"Gravado '{approved_rel}' ({note})")

        # 11-12. Registro final + memória vetorial (best-effort)
        self.store.update_interaction(
            interaction_id, status="approved" if written else "rejected"
        )
        if written and self.memory:
            self.memory.index_interaction(
                interaction_id,
                f"[edit {', '.join(written)}] {instruction}",
                proposal.explanation,
            )
        if written:
            self.ui.info(f"Interação #{interaction_id}: {len(written)} arquivo(s) gravado(s).")

    # --- helpers do fluxo de edição ------------------------------------------------

    def _explore_context(
        self, rel: str, content: str, instruction: str, provider: str | None
    ) -> dict[str, str]:
        """`edit --explore`: o Ollama local decide, via tool calling, quais
        arquivos relacionados (imports, tipos citados) ler antes de editar.
        Nunca ativa com Claude — a neutralização de ferramentas do provider
        Claude é intencional (ver providers/claude_cli_provider.py)."""
        if provider == "claude":
            self.ui.warn("--explore ignorado: só funciona com o provider Ollama.")
            return {}
        ollama = self.router.providers.get("ollama")
        if not isinstance(ollama, OllamaProvider):
            self.ui.warn("--explore ignorado: provider Ollama indisponível.")
            return {}

        explorer = ContextExplorer(
            ollama, self.root, self.settings.indexing, self.settings.context_discovery,
            system_prompt=load_prompt("explore.md"),
        )
        with self.ui.console.status("explorando arquivos relacionados…"):
            try:
                result = explorer.explore(rel, content, instruction)
            except ProviderError as e:
                self.ui.warn(f"Exploração de contexto falhou, seguindo sem contexto extra: {e}")
                return {}

        if result.files:
            self.ui.info(
                f"Exploração encontrou {len(result.files)} arquivo(s) relacionado(s): "
                + ", ".join(sorted(result.files))
            )
        if result.truncated_budget:
            self.ui.warn(
                "Orçamento de exploração esgotado (chamadas/caracteres) — "
                "contexto pode estar incompleto."
            )
        return result.files

    def _claude_available(self) -> bool:
        """False no modo offline: o provider Claude nem é registrado."""
        return "claude" in self.router.providers

    def _reject_claude_offline(self) -> None:
        self.ui.error(
            "O provider Claude está desabilitado (mode=offline). "
            "Habilite com `coder-dev config --set mode=provider` "
            "(pessoal) ou `mode=corporate` (endpoint da organização)."
        )

    def _resolve_initial_provider(
        self, provider: str | None, prompt_chars: int
    ) -> tuple[bool, str | None]:
        """Decide o provider de saída; confirma custo se for Claude.

        Retorna (prosseguir?, provider) — provider None significa usar o padrão.
        """
        if provider == "claude":
            if not self._claude_available():
                self._reject_claude_offline()
                return False, None
            return (True, "claude") if self._confirm_claude_cost(prompt_chars) else (False, None)
        reasons = self.router.escalation_reasons(prompt_chars=prompt_chars)
        if reasons and provider is None and self._claude_available():
            self.ui.warn("; ".join(reasons))
            if self.settings.router.auto_escalate or self.ui.confirm("Escalar para Claude?"):
                if self._confirm_claude_cost(prompt_chars):
                    return True, "claude"
                return False, None
        return True, provider  # None = default (ollama)

    def _confirm_claude_cost(self, prompt_chars: int) -> bool:
        if not self.settings.router.confirm_cost_before_claude:
            return True
        estimate = self.router.estimate_claude_cost(prompt_chars)
        ceiling = self.settings.providers.claude.max_budget_usd
        return self.ui.confirm(
            f"Chamada ao Claude: custo estimado ~${estimate:.3f} "
            f"(teto rígido --max-budget-usd: ${ceiling:.2f}). Continuar?"
        )

    def _escalate(self, file_arg: str, instruction: str, prompt_chars: int) -> None:
        if not self._confirm_claude_cost(prompt_chars):
            self.ui.info("Escalada cancelada.")
            return
        self.ui.info("Escalando para Claude…")
        return self.edit(file_arg, instruction, provider="claude")

    def _approve(self, changed: list[str], provider: str | None) -> list[str] | str:
        """Retorna a lista de arquivos aprovados, [] para rejeição, ou 'escalate'."""
        allow_escalate = provider != "claude" and self._claude_available()
        if len(changed) == 1:
            choice = self.ui.ask_approval(allow_escalate=allow_escalate)
            if choice == "e":
                return "escalate"
            return changed if choice == "a" else []
        choice = self.ui.ask_batch_approval(allow_escalate=allow_escalate)
        if choice == "e":
            return "escalate"
        if choice == "r":
            return []
        if choice == "a":
            return changed
        # individual
        return [rel for rel in changed if self.ui.confirm(f"Aprovar '{rel}'?")]

    def _load_targets(
        self, proposal: EditProposal, interaction_id: int
    ) -> dict[str, TargetFile] | None:
        """Valida e carrega cada arquivo da proposta. Path fora do root → aborta tudo."""
        targets: dict[str, TargetFile] = {}
        for edit in proposal.edits:
            rel = _normalize(edit.file)
            if rel in targets:
                continue
            try:
                path = validate_path(self.root, rel)
            except PathGuardError as e:
                self.store.update_interaction(interaction_id, status="rejected")
                self.ui.error(f"Proposta rejeitada — {e}")
                return None
            is_new = not path.exists()
            original = "" if is_new else path.read_text(encoding="utf-8")
            targets[rel] = TargetFile(
                rel=rel,
                path=path,
                original=original,
                original_hash=_sha256(original),
                is_new=is_new,
            )
        return targets

    def _request_proposal(
        self, user_prompt: str, system: str, provider: str | None
    ) -> tuple[EditProposal, int, str | None] | None:
        interaction_id, response = self.router.ask(
            "edit", user_prompt, system=system, provider=provider, json_mode=True
        )
        try:
            return parse_edit_proposal(response.text), interaction_id, provider
        except ParseError:
            self.store.update_interaction(interaction_id, status="parse_error")
            self.ui.warn("Resposta não era JSON válido — re-pedindo ao modelo (1 tentativa)…")

        retry_prompt = (
            user_prompt
            + "\n\nSua resposta anterior não era JSON válido. Responda apenas o JSON."
        )
        interaction_id, response = self.router.ask(
            "edit", retry_prompt, system=system, provider=provider, json_mode=True
        )
        try:
            return parse_edit_proposal(response.text), interaction_id, provider
        except ParseError as e:
            self.store.update_interaction(interaction_id, status="parse_error")
            self.ui.error(f"Modelo não retornou JSON válido após re-tentativa.\n{e}")

        # Política V2: duas falhas consecutivas de parse → oferecer escalada
        reasons = self.router.escalation_reasons(parse_failures=2)
        if provider != "claude" and reasons and self._claude_available():
            self.ui.warn("; ".join(reasons))
            if self.ui.confirm("Escalar esta tarefa para Claude?"):
                if not self._confirm_claude_cost(len(user_prompt)):
                    return None
                interaction_id, response = self.router.ask(
                    "edit", user_prompt, system=system, provider="claude", json_mode=True
                )
                try:
                    return parse_edit_proposal(response.text), interaction_id, "claude"
                except ParseError as e:
                    self.store.update_interaction(interaction_id, status="parse_error")
                    self.ui.error(f"Claude também não retornou JSON válido. Abortado.\n{e}")
        return None

    def _show_plan(
        self, rel: str, content: str, instruction: str, provider: str | None
    ) -> bool:
        """Gera e exibe o plano em passos; retorna False para abortar."""
        prompt = (
            f"Arquivo alvo: {rel}\n\nTrecho inicial do arquivo:\n```\n{content[:4000]}\n```\n\n"
            f"Tarefa: {instruction}"
        )
        _, response = self.router.ask(
            "plan", prompt, system=load_prompt("plan.md"), provider=provider
        )
        self.ui.print_markdown(response.text)
        return self.ui.confirm("Prosseguir com a edição seguindo este plano?")

    # --- ask ------------------------------------------------------------------

    def ask(self, question: str, provider: str | None = None) -> None:
        system = load_prompt("ask.md")
        prompt = build_ask_prompt(question, self.root.name)
        if provider == "claude":
            if not self._claude_available():
                self._reject_claude_offline()
                return
            if not self._confirm_claude_cost(len(prompt)):
                return
        interaction_id, response = self.router.ask(
            "ask", prompt, system=system, provider=provider
        )
        self.ui.print_markdown(response.text)
        if self.memory:
            self.memory.index_interaction(interaction_id, question, response.text)

    # --- decisões arquiteturais (V2) -----------------------------------------------

    def decision(self, text: str, tags: list[str] | None = None) -> None:
        """Registra um documento de decisão (um por decisão — seção 12)."""
        interaction_id = self.store.record_interaction(
            project_id=self.project_id,
            task_type="decision",
            provider="user",
            model="-",
            prompt=text,
            status="ok",
            git_branch=self.router.git_branch,
        )
        for tag in tags or []:
            self.store.add_tag(interaction_id, tag)
        if self.memory:
            self.memory.index_decision(interaction_id, text, tags)
        self.ui.success(f"Decisão registrada como interação #{interaction_id}.")

    # --- undo -----------------------------------------------------------------

    def undo(self, list_only: bool = False) -> None:
        if list_only:
            entries = self.backups.undo_entries()
            if not entries:
                self.ui.info("Pilha de undo vazia para este projeto.")
                return
            self.ui.show_undo_list(entries)
            return

        entry = self.backups.peek_undo()
        if entry is None:
            self.ui.info("Nada para desfazer neste projeto.")
            return

        target = Path(entry["file"])
        rel = (
            str(target.relative_to(self.root))
            if target.is_relative_to(self.root)
            else str(target)
        )
        current = target.read_text(encoding="utf-8") if target.exists() else ""

        if entry["backup"] is None:
            # Arquivo foi criado do zero — undo = removê-lo
            self.ui.warn(f"'{rel}' foi criado pela última edição. Undo irá removê-lo.")
            if not self.ui.confirm(f"Remover '{rel}'?"):
                self.ui.info("Undo cancelado.")
                return
            target.unlink(missing_ok=True)
            self.backups.pop_undo()
            self.ui.success(f"Removido '{rel}'.")
            return

        backup_path = Path(entry["backup"])
        if not backup_path.exists():
            self.ui.error(f"Backup não encontrado: {backup_path}. Undo abortado.")
            return
        restored = backup_path.read_text(encoding="utf-8")
        diff = unified_diff(current, restored, rel)
        if not diff:
            self.ui.info("O arquivo já está idêntico ao backup. Nada a fazer.")
            self.backups.pop_undo()
            return
        self.ui.show_diff(diff)
        if not self.ui.confirm(f"Restaurar '{rel}' para o backup de {entry['timestamp']}?"):
            self.ui.info("Undo cancelado.")
            return
        # Backup do estado atual antes de restaurar (permite "desfazer o undo")
        if target.exists():
            self.backups.create(self.root, target)
        atomic_write(target, restored)
        self.backups.pop_undo()
        self.ui.success(f"Restaurado '{rel}' a partir de {backup_path.name}.")
