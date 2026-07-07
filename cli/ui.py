"""Camada de apresentação — Rich para diff colorido, tabelas e prompts."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text


class UI:
    def __init__(self):
        self.console = Console()

    # --- mensagens -------------------------------------------------------------

    def info(self, message: str) -> None:
        self.console.print(f"[cyan]ℹ[/cyan] {message}")

    def warn(self, message: str) -> None:
        self.console.print(f"[yellow]⚠[/yellow] {message}")

    def error(self, message: str) -> None:
        self.console.print(f"[red]✗[/red] {message}")

    def success(self, message: str) -> None:
        self.console.print(f"[green]✓[/green] {message}")

    def print_markdown(self, text: str) -> None:
        self.console.print(Markdown(text))

    def print_raw(self, text: str) -> None:
        self.console.print(text)

    # --- diff e proposta ---------------------------------------------------------

    def show_diff(self, diff: str, title: str = "diff proposto") -> None:
        rendered = Text()
        for line in diff.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                rendered.append(line + "\n", style="bold white")
            elif line.startswith("@@"):
                rendered.append(line + "\n", style="cyan")
            elif line.startswith("+"):
                rendered.append(line + "\n", style="green")
            elif line.startswith("-"):
                rendered.append(line + "\n", style="red")
            else:
                rendered.append(line + "\n", style="dim")
        self.console.print(Panel(rendered, title=escape(title), border_style="blue"))

    def show_explanation(
        self, explanation: str, confidence: float, files: list[str] | None = None
    ) -> None:
        color = "green" if confidence >= 0.8 else "yellow" if confidence >= 0.6 else "red"
        files_line = (
            f"\n[bold]arquivos:[/bold] {escape(', '.join(files))}" if files else ""
        )
        self.console.print(
            Panel(
                f"{escape(explanation)}\n\n[bold]confidence:[/bold] "
                f"[{color}]{confidence:.2f}[/{color}]{files_line}",
                title="proposta do modelo",
                border_style="magenta",
            )
        )

    def ask_approval(self, allow_escalate: bool = True) -> str:
        if allow_escalate:
            return Prompt.ask(
                "[bold][a][/bold]provar / [bold][r][/bold]ejeitar / [bold][e][/bold]scalar para Claude",
                choices=["a", "r", "e"],
                default="r",
            )
        return Prompt.ask(
            "[bold][a][/bold]provar / [bold][r][/bold]ejeitar",
            choices=["a", "r"],
            default="r",
        )

    def ask_batch_approval(self, allow_escalate: bool = True) -> str:
        """Aprovação multi-arquivo: tudo, individual, rejeitar, escalar."""
        choices = ["a", "i", "r"] + (["e"] if allow_escalate else [])
        label = (
            "[bold][a][/bold]provar tudo / [bold][i][/bold]ndividual / [bold][r][/bold]ejeitar"
            + (" / [bold][e][/bold]scalar" if allow_escalate else "")
        )
        return Prompt.ask(label, choices=choices, default="r")

    def confirm(self, message: str) -> bool:
        return Confirm.ask(message, default=False)

    # --- tabelas -------------------------------------------------------------

    def show_history(self, rows: list[dict]) -> None:
        table = Table(title="histórico de interações")
        for column in ("#", "quando", "projeto", "tarefa", "provider", "modelo", "status", "conf.", "custo"):
            table.add_column(column)
        status_styles = {
            "approved": "green", "ok": "cyan", "rejected": "yellow",
            "parse_error": "red", "provider_error": "red",
        }
        for row in rows:
            status = row["status"]
            table.add_row(
                str(row["id"]),
                row["timestamp"],
                row.get("project_name") or "-",
                row["task_type"],
                row["provider"],
                row["model"],
                f"[{status_styles.get(status, 'white')}]{status}[/]",
                f"{row['confidence']:.2f}" if row["confidence"] is not None else "-",
                f"${row['cost_estimate']:.4f}" if row["cost_estimate"] else "$0",
            )
        self.console.print(table)

    def show_recall(self, hits, degraded: bool = False) -> None:
        if degraded:
            self.warn("Memória vetorial indisponível — resultados por palavra-chave (FTS5).")
        if not hits:
            self.info("Nenhum resultado. O projeto já foi indexado? (`aider index .`)")
            return
        for i, hit in enumerate(hits, 1):
            score = f"{hit.score:.2f}" if hit.score else "fts"
            tags = f"  [dim]tags: {', '.join(hit.tags)}[/dim]" if hit.tags else ""
            header = (
                f"[bold]{i}.[/bold] {escape('[' + hit.type + ']')} {escape(hit.source)}  "
                f"[dim]{hit.timestamp}[/dim]  score={score}{tags}"
            )
            self.console.print(
                Panel(escape(hit.snippet), title=header, border_style="blue", title_align="left")
            )

    def show_index_report(self, report) -> None:
        self.success(
            f"Indexação concluída: {report.indexed_files} arquivo(s) indexado(s), "
            f"{report.chunks} chunk(s), {report.unchanged} inalterado(s), "
            f"{report.skipped} pulado(s)."
        )
        for error in report.errors:
            self.warn(f"erro: {error}")

    def show_stats(self, stats: dict, vector_count: int | None = None) -> None:
        totals = stats["totals"]
        self.console.print(
            Panel(
                f"prompts: [bold]{totals['prompts']}[/bold]   "
                f"tokens in/out: [bold]{totals['tokens_in']}[/bold]/[bold]{totals['tokens_out']}[/bold]   "
                f"custo acumulado: [bold]${totals['cost']:.4f}[/bold]"
                + (f"   vetores: [bold]{vector_count}[/bold]" if vector_count is not None else ""),
                title="totais",
                border_style="green",
            )
        )
        table = Table(title="por provider/modelo")
        for column in ("provider", "modelo", "usos", "tempo médio", "sucesso", "custo"):
            table.add_column(column)
        for row in stats["by_provider"]:
            success_rate = (row["successes"] or 0) / row["uses"] * 100 if row["uses"] else 0
            table.add_row(
                row["provider"], row["model"], str(row["uses"]),
                f"{row['avg_ms']} ms" if row["avg_ms"] is not None else "-",
                f"{success_rate:.0f}%", f"${row['cost']:.4f}",
            )
        self.console.print(table)

        edits = stats["edits"]
        total_edits = edits["total_edits"] or 0
        total_prompts = totals["prompts"] or 0
        rejection = (edits["rejected"] or 0) / total_edits * 100 if total_edits else 0
        escalation = (edits["claude_calls"] or 0) / total_prompts * 100 if total_prompts else 0
        self.console.print(
            f"edits: {total_edits} (aprovados: {edits['approved'] or 0}, "
            f"rejeitados: {edits['rejected'] or 0} — taxa de rejeição {rejection:.0f}%)   "
            f"escalada para Claude: {escalation:.0f}%"
        )

        if stats["top_files"]:
            table = Table(title="arquivos mais alterados")
            table.add_column("arquivo")
            table.add_column("projeto")
            table.add_column("edições")
            for row in stats["top_files"]:
                table.add_row(row["path"], row.get("project_name") or "-", str(row["edits"]))
            self.console.print(table)
        if stats["top_projects"]:
            table = Table(title="projetos mais ativos")
            table.add_column("projeto")
            table.add_column("interações")
            for row in stats["top_projects"]:
                table.add_row(row["name"], str(row["interactions"]))
            self.console.print(table)

    def show_undo_list(self, entries: list[dict]) -> None:
        table = Table(title="pilha de undo (mais recente por último)")
        table.add_column("#")
        table.add_column("arquivo")
        table.add_column("quando")
        table.add_column("backup")
        for i, entry in enumerate(entries, 1):
            table.add_row(
                str(i),
                entry["file"],
                entry["timestamp"],
                entry["backup"] or "(arquivo criado — undo remove)",
            )
        self.console.print(table)
