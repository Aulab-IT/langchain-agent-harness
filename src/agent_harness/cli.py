from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_harness.config import Settings
from agent_harness.evaluation import CaseResult, execute_eval_case, load_eval_cases, summarize
from agent_harness.factory import build_harness
from agent_harness.improve import run_improvement
from agent_harness.runner import GoalRunner

app = typer.Typer(help="Agent harness didattico con LangChain.")
console = Console()


def command_ok(arguments: list[str]) -> bool:
    try:
        return subprocess.run(arguments, capture_output=True, check=False).returncode == 0
    except FileNotFoundError:
        return False


def _payload_wants_network(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("with_network") is True:
            return True
        return any(_payload_wants_network(nested) for nested in value.values())
    if isinstance(value, list):
        return any(_payload_wants_network(nested) for nested in value)
    return False


async def ask_approval(payload: dict[str, Any]) -> bool:
    wants_network = _payload_wants_network(payload)
    title = "Accesso rete sandbox" if wants_network else "Approvazione"
    console.print(Panel(json.dumps(payload, indent=2, ensure_ascii=False), title=title))
    if wants_network:
        console.print(
            "[yellow]Concede accesso rete temporaneo al container, solo per questo "
            "comando. La rete viene revocata subito dopo.[/yellow]"
        )
        return typer.confirm("Concedere accesso rete per questo comando?", default=False)
    return typer.confirm("Approvare questa operazione?", default=False)


async def execute_goal(goal: str, thread_id: str) -> None:
    async with build_harness() as harness:
        result = await GoalRunner(harness, ask_approval).run(goal, thread_id=thread_id)
        console.print(result.text)
        if not result.completed:
            console.print(
                "[yellow]Budget di continuazione esaurito senza marcatore GOAL_COMPLETE.[/yellow]"
            )


@app.command()
def run(
    goal: str = typer.Argument(..., help="Obiettivo assegnato all'agente."),
    thread_id: str = typer.Option("", help="ID thread; se omesso viene generato."),
) -> None:
    """Esegue un singolo obiettivo."""
    asyncio.run(execute_goal(goal, thread_id or str(uuid.uuid4())))


@app.command()
def chat(
    thread_id: str = typer.Option("", help="ID persistente della conversazione."),
) -> None:
    """Avvia una chat; ogni riga viene eseguita sullo stesso thread."""
    active_thread = thread_id or str(uuid.uuid4())
    console.print(f"Thread: [cyan]{active_thread}[/cyan]. Scrivi /exit per terminare.")
    while True:
        try:
            text = console.input("[bold green]tu> [/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text in {"/exit", "/quit"}:
            break
        if text:
            asyncio.run(execute_goal(text, active_thread))


@app.command()
def improve(
    since: int = typer.Option(100, help="Numero di run terminali recenti da analizzare."),
) -> None:
    """Loop hill-climbing: analizza i trace e propone modifiche alla config dell'harness."""
    result = asyncio.run(run_improvement(Settings(), since=since))
    console.print(Panel(str(result["report"]), title="Report trace"))
    if result["summary"]:
        console.print(f"[bold]Sintesi:[/bold] {result['summary']}")
    console.print(f"Proposta salvata: [cyan]{result['path']}[/cyan]")
    console.print("[dim]Propose-only. Valuta e promuovi dal Control Center.[/dim]")


# `typer.Option` non può stare in un default valutato all'import (ruff B008).
_CASES_OPTION = typer.Option(Path("evals/cases.json"), help="File dei casi.")


async def _run_eval(settings: Settings, only: str | None, cases_path: Path) -> list[CaseResult]:
    cases = load_eval_cases(cases_path)
    if only:
        wanted = {name.strip() for name in only.split(",") if name.strip()}
        cases = [case for case in cases if case.id in wanted]
        if not cases:
            raise typer.BadParameter(f"Nessun caso con id in {sorted(wanted)}")
    root = settings.state_dir / "evaluations" / "baseline-run"
    results: list[CaseResult] = []
    for index, case in enumerate(cases, start=1):
        console.print(f"[dim]({index}/{len(cases)})[/dim] {case.id}…")
        # Un solo braccio: nessun candidato da confrontare, si misura la baseline così com'è.
        results.append(await execute_eval_case(settings, case, {}, "baseline", root))
    return results


@app.command()
def eval(
    only: str = typer.Option("", help="Esegui solo questi id, separati da virgola."),
    cases: Path = _CASES_OPTION,
) -> None:
    """Esegue l'eval set con l'harness reale e stampa i risultati caso per caso.

    Costa: ogni caso è un run completo, con chiamate al modello e alla sandbox. Serve a sapere
    se i check discriminano e se il grader è rumoroso, prima di fidarsi del gate di promozione.
    """
    settings = Settings()
    results = asyncio.run(_run_eval(settings, only or None, cases))

    table = Table(title="Eval baseline")
    table.add_column("caso")
    table.add_column("check", justify="center")
    table.add_column("score", justify="right")
    table.add_column("grader", justify="right")
    table.add_column("iter", justify="right")
    table.add_column("token", justify="right")
    table.add_column("tempo", justify="right")
    for result in results:
        grader = ", ".join(f"{score:.2f}" for score in result.grader_scores) or "—"
        table.add_row(
            result.case_id,
            "[green]✓[/green]" if result.checks_passed else "[red]✗[/red]",
            f"{result.check_score:.2f}",
            grader,
            str(result.iterations),
            f"{result.tokens:,}",
            f"{result.elapsed_ms / 1000:.1f}s",
        )
    console.print(table)

    summary = summarize(results)
    console.print(
        f"[bold]check pass rate[/bold] {summary.check_pass_rate:.0%} · "
        f"[bold]score medio[/bold] {summary.avg_check_score:.2f} · "
        f"[bold]completion[/bold] {summary.completion_rate:.0%} · "
        f"[bold]token[/bold] {summary.total_tokens:,} · "
        f"[bold]tempo[/bold] {summary.elapsed_ms / 1000:.0f}s"
    )
    for result in results:
        if result.check_failures:
            console.print(f"[red]{result.case_id}[/red]: " + "; ".join(result.check_failures))


@app.command()
def doctor() -> None:
    """Controlla configurazione e prerequisiti senza chiamare il modello."""
    settings = Settings()
    checks = {
        "OPENAI_API_KEY": bool(settings.openai_api_key),
        "workspace": settings.workspace_dir.exists(),
        "Docker daemon": command_ok(["docker", "version"]),
    }
    for name, ok in checks.items():
        console.print(f"{'✓' if ok else '✗'} {name}")
    image_ready = command_ok(["docker", "image", "inspect", settings.harness_sandbox_image])
    console.print(
        f"{'✓' if image_ready else '○'} Immagine {settings.harness_sandbox_image} "
        f"({'presente' if image_ready else 'verrà costruita al primo docker_exec'})"
    )
    if not all(checks.values()):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
