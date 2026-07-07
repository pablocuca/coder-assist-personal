"""Agent — orquestra o fluxo de edição (seção 9).

proposta → diff → aprovação explícita → re-verificação de hash → backup →
gravação atômica → registro. A IA nunca grava diretamente (princípio 1).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from cli.ui import UI
from core.backup import BackupManager
from core.context_builder import build_ask_prompt, build_edit_prompt
from core.diff_engine import unified_diff
from core.errors import ParseError, PatchError
from core.patch_engine import apply_search_replace, atomic_write, check_replace_file_allowed
from core.router import Router
from core.settings import Settings, load_prompt
from git_tools.git_manager import is_file_dirty
from memory.memory_manager import MemoryManager
from memory.sqlite_store import SQLiteStore
from models.schemas import EditProposal, parse_edit_proposal
from security.path_guard import validate_path

logger = logging.getLogger(__name__)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


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

    def edit(self, file_arg: str, instruction: str, provider: str | None = None) -> None:
        # 1. Validar path e ler arquivo
        path = validate_path(self.root, file_arg)
        rel = str(path.relative_to(self.root))
        is_new = not path.exists()
        original = "" if is_new else path.read_text(encoding="utf-8")
        original_hash = _sha256(original)

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

        # 2-6. Contexto → Router → parse com uma re-tentativa guiada
        system = load_prompt("edit.md")
        user_prompt = build_edit_prompt(rel, original, instruction, is_new)
        result = self._request_proposal(user_prompt, system, provider)
        if result is None:
            return
        proposal, interaction_id = result
        self.store.update_interaction(interaction_id, confidence=proposal.confidence)

        # MVP: comando edita um único arquivo (multi-arquivo é V2)
        foreign = [e.file for e in proposal.edits if e.file.strip("./") != rel.strip("./")]
        if foreign:
            self.store.update_interaction(interaction_id, status="parse_error")
            self.ui.error(
                f"A proposta referencia outro(s) arquivo(s) {foreign}; este comando "
                f"edita apenas '{rel}'. Edição multi-arquivo chega na V2. Abortado."
            )
            return

        # 7. Aplicar edits em memória (nunca no disco ainda)
        updated, ok = self._apply_edits(original, proposal, is_new, interaction_id)
        if not ok:
            return

        diff = unified_diff(original, updated, rel)
        if not diff:
            self.ui.info("A proposta não altera o arquivo. Nada a fazer.")
            return

        # 8-9. Exibir diff + confidence + explanation, pedir aprovação
        self.ui.show_proposal(diff, proposal.explanation, proposal.confidence)
        if provider != "claude" and self.router.should_escalate(proposal.confidence):
            self.ui.warn(
                f"Confiança {proposal.confidence:.2f} abaixo do limiar "
                f"{self.settings.router.confidence_threshold:.2f} — considere [e]scalar."
            )
        choice = self.ui.ask_approval()

        if choice == "r":
            self.store.update_interaction(interaction_id, status="rejected")
            self.ui.info("Proposta rejeitada. Nenhum arquivo foi alterado.")
            return
        if choice == "e":
            self.store.update_interaction(interaction_id, status="rejected")
            self.ui.info("Escalando para Claude…")
            return self.edit(file_arg, instruction, provider="claude")

        # 10a. Re-verificar hash — arquivo pode ter mudado externamente
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if _sha256(current) != original_hash:
            self.store.update_interaction(interaction_id, status="rejected")
            self.ui.error(
                f"'{rel}' mudou no disco desde a leitura. Abortado sem gravar — "
                "repita o edit."
            )
            return

        # 10b-c. Backup + gravação atômica
        backup = None if is_new else self.backups.create(self.root, path)
        atomic_write(path, updated)
        self.backups.push_undo(path, backup)

        # 11. Registro final
        self.store.update_interaction(interaction_id, status="approved")
        file_id = self.store.upsert_file(self.project_id, rel, _sha256(updated))
        self.store.link_interaction_file(interaction_id, file_id)

        # 12. (V1) Memória vetorial — best-effort, nunca bloqueia a edição
        if self.memory:
            self.memory.index_interaction(
                interaction_id, f"[edit {rel}] {instruction}", proposal.explanation
            )

        note = f" (backup: {backup.name})" if backup else " (arquivo novo)"
        self.ui.success(f"Gravado '{rel}'{note} — interação #{interaction_id}")

    def _request_proposal(
        self, user_prompt: str, system: str, provider: str | None
    ) -> tuple[EditProposal, int] | None:
        interaction_id, response = self.router.ask(
            "edit", user_prompt, system=system, provider=provider, json_mode=True
        )
        try:
            return parse_edit_proposal(response.text), interaction_id
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
            return parse_edit_proposal(response.text), interaction_id
        except ParseError as e:
            self.store.update_interaction(interaction_id, status="parse_error")
            self.ui.error(f"Modelo não retornou JSON válido após re-tentativa. Abortado.\n{e}")
            return None

    def _apply_edits(
        self, original: str, proposal: EditProposal, is_new: bool, interaction_id: int
    ) -> tuple[str, bool]:
        """Aplica cada edit em memória; falhas parciais pedem decisão ao usuário."""
        updated = original
        applied, failed = 0, []
        for edit in proposal.edits:
            try:
                if edit.replace_file is not None:
                    check_replace_file_allowed(original, is_new)
                    updated = edit.replace_file
                else:
                    updated = apply_search_replace(updated, edit.search, edit.replace)
                applied += 1
            except PatchError as e:
                failed.append(e)

        if failed:
            for error in failed:
                self.ui.error(str(error))
            if applied == 0:
                self.store.update_interaction(interaction_id, status="rejected")
                self.ui.error("Nenhum edit pôde ser aplicado. Operação abortada.")
                return original, False
            if not self.ui.confirm(
                f"{len(failed)} edit(s) falharam e {applied} aplicaram. "
                "Continuar apenas com os que aplicaram?"
            ):
                self.store.update_interaction(interaction_id, status="rejected")
                self.ui.info("Operação cancelada.")
                return original, False
        return updated, True

    # --- ask ------------------------------------------------------------------

    def ask(self, question: str, provider: str | None = None) -> None:
        system = load_prompt("ask.md")
        prompt = build_ask_prompt(question, self.root.name)
        interaction_id, response = self.router.ask(
            "ask", prompt, system=system, provider=provider
        )
        self.ui.print_markdown(response.text)
        if self.memory:
            self.memory.index_interaction(interaction_id, question, response.text)

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
