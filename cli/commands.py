"""Comandos da CLI (seção 20).

MVP: edit, ask, history, undo, config, tag.
V1:  index, recall, stats, commit. (recall --synthesize e busca híbrida: V2)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
import yaml

from cli.ui import UI
from core.agent import Agent
from core.errors import AiderError, ProviderError, VectorStoreError
from core.logging_setup import setup_logging
from core.router import Router
from core.settings import load_prompt, load_settings, user_config_path
from git_tools import git_history
from git_tools.git_manager import current_branch, find_project_root
from memory.memory_manager import MemoryManager
from memory.retriever import Retriever
from memory.sqlite_store import SQLiteStore
from providers.claude_cli_provider import ClaudeCliProvider
from providers.ollama_provider import OllamaProvider

app = typer.Typer(
    help="Aider Pessoal — edição de código assistida por IA, local-first e auditável.",
    no_args_is_help=True,
    add_completion=False,
)
ui = UI()


class AppContext:
    """Monta toda a cadeia: settings → store → projeto → providers → router → agent."""

    def __init__(self):
        self.settings = load_settings()
        state = self.settings.state_dir
        for sub in ("db", "logs", "backups", "config"):
            (state / sub).mkdir(parents=True, exist_ok=True)
        setup_logging(state / "logs", self.settings.logging)

        self.store = SQLiteStore(state / "db" / "database.sqlite")
        self.root = find_project_root(Path.cwd())
        self.project_id = self.store.get_or_create_project(self.root.name, str(self.root))
        self.branch = current_branch(self.root)
        if self.branch is None:
            ui.warn("Projeto sem Git — recursos Git desabilitados (histórico continua normal).")

        providers = {
            "ollama": OllamaProvider(self.settings.providers.ollama),
            "claude": ClaudeCliProvider(self.settings.providers.claude),
        }
        self.router = Router(
            self.settings,
            self.store,
            providers,
            project_id=self.project_id,
            git_branch=self.branch,
        )
        # MemoryManager é barato de construir — ChromaDB só é aberto no primeiro uso
        self.memory = MemoryManager(
            self.settings, self.store, self.root, self.project_id, self.root.name
        )
        self.agent = Agent(
            self.settings, self.store, self.router, ui, self.root, self.project_id,
            memory=self.memory,
        )


def _ctx() -> AppContext:
    try:
        return AppContext()
    except AiderError as e:
        ui.error(str(e))
        raise typer.Exit(1)


def _guarded(fn) -> None:
    try:
        fn()
    except AiderError as e:
        ui.error(str(e))
        raise typer.Exit(1)
    except KeyboardInterrupt:
        ui.info("Interrompido. Nenhum arquivo foi corrompido (escrita é atômica).")
        raise typer.Exit(130)


@app.command()
def edit(
    arquivo: str = typer.Argument(..., help="Arquivo a editar (relativo à raiz do projeto)"),
    provider: Optional[str] = typer.Option(None, "--provider", help="ollama | claude"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Instrução de edição"),
):
    """Edita um arquivo: proposta da IA → diff → aprovação → backup → gravação."""
    ctx = _ctx()
    instruction = message or typer.prompt("Instrução")
    _guarded(lambda: ctx.agent.edit(arquivo, instruction, provider=provider))


@app.command()
def ask(
    pergunta: Optional[str] = typer.Argument(None, help="Pergunta livre com contexto do projeto"),
    provider: Optional[str] = typer.Option(None, "--provider", help="ollama | claude"),
):
    """Chat livre — nada é gravado em arquivos, tudo registrado no histórico."""
    ctx = _ctx()
    question = pergunta or typer.prompt("Pergunta")
    _guarded(lambda: ctx.agent.ask(question, provider=provider))


@app.command()
def history(
    project: Optional[str] = typer.Option(None, "--project", help="Filtrar por projeto"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filtrar por tag"),
    n: int = typer.Option(20, "-n", help="Quantidade de interações"),
):
    """Histórico de interações registradas pelo Router."""
    ctx = _ctx()
    rows = ctx.store.history(project=project, tag=tag, limit=n)
    if not rows:
        ui.info("Nenhuma interação registrada ainda.")
        return
    ui.show_history(rows)


@app.command()
def undo(
    list_backups: bool = typer.Option(False, "--list", help="Listar a pilha de undo"),
):
    """Desfaz a última edição gravada, restaurando o backup (com diff e confirmação)."""
    ctx = _ctx()
    _guarded(lambda: ctx.agent.undo(list_only=list_backups))


@app.command()
def tag(
    interaction_id: int = typer.Argument(..., help="ID da interação (ver `aider history`)"),
    nome: str = typer.Argument(..., help="Nome da tag (livre, criada sob demanda)"),
):
    """Aplica uma tag a uma interação, para filtrar em history/recall."""
    ctx = _ctx()
    if ctx.store.get_interaction(interaction_id) is None:
        ui.error(f"Interação #{interaction_id} não existe.")
        raise typer.Exit(1)
    ctx.store.add_tag(interaction_id, nome)
    ui.success(f"Tag '{nome}' aplicada à interação #{interaction_id}.")


@app.command()
def index(
    caminho: str = typer.Argument(".", help="Sempre indexa a raiz do projeto detectado"),
    full: bool = typer.Option(False, "--full", help="Força re-indexação completa"),
):
    """Indexa o projeto no banco vetorial (incremental por hash; --full re-indexa tudo)."""
    ctx = _ctx()
    if caminho not in (".", str(ctx.root)):
        ui.warn(f"A indexação é sempre da raiz do projeto detectado: {ctx.root}")

    def run() -> None:
        with ui.console.status("indexando…") as status:
            report = ctx.memory.index_project(
                full=full, progress=lambda rel: status.update(f"indexando {rel}")
            )
        ui.show_index_report(report)

    _guarded(run)


@app.command()
def recall(
    query: Optional[str] = typer.Argument(None, help="Busca semântica no conhecimento acumulado"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Listar interações com esta tag"),
    k: int = typer.Option(5, "-k", help="Quantidade de resultados"),
):
    """Recupera conhecimento acumulado (busca vetorial com fontes; FTS5 como degradação)."""
    ctx = _ctx()
    if tag:
        rows = ctx.store.history(tag=tag, limit=k)
        if not rows:
            ui.info(f"Nenhuma interação com a tag '{tag}'.")
            return
        ui.show_history(rows)
        return
    if not query:
        ui.error("Informe uma query ou --tag.")
        raise typer.Exit(1)

    try:
        retriever = Retriever(ctx.memory.vectors, ctx.memory.embedder, ctx.store)
        hits = retriever.recall(query, k=k)
        ui.show_recall(hits)
    except (VectorStoreError, ProviderError) as e:
        # Degradação (seção 19): vetorial indisponível → busca por palavra-chave
        ui.warn(str(e))
        fallback = Retriever(None, ctx.memory.embedder, ctx.store)
        hits = fallback.recall_keyword(query, k=k)
        ui.show_recall(hits, degraded=True)


@app.command()
def stats(
    project: Optional[str] = typer.Option(None, "--project", help="Filtrar por projeto"),
    since: Optional[str] = typer.Option(None, "--since", help="Janela de tempo, ex.: 30d, 2w, 12h"),
):
    """Observabilidade: totais, uso por provider, taxas de rejeição/escalada, top arquivos."""
    ctx = _ctx()
    since_iso = _parse_since(since) if since else None
    data = ctx.store.stats(project=project, since=since_iso)
    ui.show_stats(data, vector_count=ctx.memory.vector_count())


@app.command()
def commit():
    """Commit assistido: mensagem sugerida pela IA, editável — nunca automática, nunca push."""
    ctx = _ctx()
    if not git_history.is_repo(ctx.root):
        ui.error("Este projeto não é um repositório Git.")
        raise typer.Exit(1)

    def run() -> None:
        status = git_history.status_porcelain(ctx.root)
        if not status.strip():
            ui.info("Nada a commitar — working tree limpo.")
            return
        if not git_history.has_staged_changes(ctx.root):
            ui.print_raw(status)
            if not ui.confirm("Nada em stage. Adicionar TODAS as alterações acima (git add -A)?"):
                ui.info("Commit cancelado. Faça `git add` do que quiser commitar e repita.")
                return
            git_history.stage_all(ctx.root)

        diff = git_history.staged_diff(ctx.root)
        interaction_id, response = ctx.router.ask(
            "commit_message",
            f"Gere a mensagem de commit para o diff abaixo:\n\n{diff}",
            system=load_prompt("commit.md"),
        )
        suggested = response.text.strip().splitlines()[0][:72] if response.text.strip() else ""
        message = typer.prompt("Mensagem do commit", default=suggested)
        if not ui.confirm(f"Commitar com a mensagem: '{message}'?"):
            ui.info("Commit cancelado (as alterações continuam em stage).")
            return
        commit_hash = git_history.commit(ctx.root, message)
        ctx.store.record_commit(
            ctx.project_id, commit_hash, ctx.branch, message, interaction_id
        )
        ui.success(f"Commit {commit_hash[:8]} criado e registrado no histórico.")

    _guarded(run)


def _parse_since(value: str) -> str:
    """'30d' / '2w' / '12h' → timestamp ISO UTC (interactions usa datetime('now'))."""
    units = {"d": "days", "w": "weeks", "h": "hours"}
    unit = value[-1].lower()
    if unit not in units or not value[:-1].isdigit():
        raise typer.BadParameter("Formato esperado: <número><d|w|h>, ex.: 30d")
    delta = timedelta(**{units[unit]: int(value[:-1])})
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%d %H:%M:%S")


@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Exibir configuração efetiva"),
    set_value: Optional[str] = typer.Option(
        None, "--set", help="Definir override local, ex.: providers.ollama.model=llama3"
    ),
):
    """Exibe a configuração efetiva ou grava um override local (~/.personal-aider)."""
    ctx = _ctx()
    if set_value:
        if "=" not in set_value:
            ui.error("Formato esperado: chave.aninhada=valor")
            raise typer.Exit(1)
        dotted_key, _, raw_value = set_value.partition("=")
        keys = dotted_key.strip().split(".")
        value = yaml.safe_load(raw_value.strip())

        override_file = user_config_path(ctx.settings.state_dir)
        data = {}
        if override_file.exists():
            data = yaml.safe_load(override_file.read_text(encoding="utf-8")) or {}
        node = data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        override_file.parent.mkdir(parents=True, exist_ok=True)
        override_file.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        ui.success(f"Override gravado em {override_file}: {dotted_key} = {value!r}")
        # Revalida imediatamente para detectar config inválida na hora do --set
        _guarded(lambda: load_settings())
        return

    dump = ctx.settings.model_dump(mode="json")
    ui.print_raw(yaml.safe_dump(dump, allow_unicode=True, sort_keys=False))
