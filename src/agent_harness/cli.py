from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
import warnings
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_harness.config import Settings
from agent_harness.evaluation import CaseResult, execute_eval_case, load_eval_cases, summarize
from agent_harness.factory import build_harness
from agent_harness.improve import run_improvement
from agent_harness.run_budget import BudgetExceededError
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
    _silence_openai_serializer_warnings()
    async with build_harness() as harness:
        try:
            result = await GoalRunner(harness, ask_approval).run(goal, thread_id=thread_id)
        except BudgetExceededError as exc:
            console.print(f"[yellow]Run fermato per budget: {exc}[/yellow]")
            return
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


def _silence_openai_serializer_warnings() -> None:
    """Zittisce gli avvisi di serializzazione di pydantic emessi dal client OpenAI.

    Il client dichiara `output` come unione di una trentina di tipi (chiamate MCP, code
    interpreter, shell locale…). Ogni risposta ne è uno solo, e pydantic avvisa per tutti gli
    altri. Sono venti righe per chiamata, non riguardano il nostro codice e non cambiano il
    risultato: coprirebbero la tabella dell'eval. Il filtro è sul messaggio, non sulla
    categoria, così gli altri `UserWarning` continuano ad arrivare.
    """
    warnings.filterwarnings(
        "ignore", message="Pydantic serializer warnings", category=UserWarning
    )


async def _run_eval(
    settings: Settings, only: str | None, cases_path: Path, repeat: int
) -> list[CaseResult]:
    _silence_openai_serializer_warnings()
    cases = load_eval_cases(cases_path)
    if only:
        wanted = {name.strip() for name in only.split(",") if name.strip()}
        cases = [case for case in cases if case.id in wanted]
        if not cases:
            raise typer.BadParameter(f"Nessun caso con id in {sorted(wanted)}")
    # Radice nuova a ogni invocazione, e sotto-radice per ogni giro. `execute_eval_case` fa
    # rmtree della cartella del caso prima di ricrearla: su macOS, Docker Desktop rifiuta di
    # bind-montare un percorso che ha già montato e che nel frattempo è stato cancellato e
    # ricreato. Riusare una radice fissa faceva fallire ogni run successivo al primo, con un
    # errore che sembrava colpa del modello.
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = settings.state_dir / "evaluations" / f"baseline-{stamp}"
    results: list[CaseResult] = []
    totale = len(cases) * repeat
    fatti = 0
    for giro in range(repeat):
        root = base / f"giro-{giro + 1}" if repeat > 1 else base
        for case in cases:
            fatti += 1
            suffisso = f" [dim](giro {giro + 1}/{repeat})[/dim]" if repeat > 1 else ""
            console.print(f"[dim]({fatti}/{totale})[/dim] {case.id}…{suffisso}")
            # Un braccio solo: nessun candidato da confrontare, si misura la baseline com'è.
            results.append(await execute_eval_case(settings, case, {}, "baseline", root))
    return results


def _aggregate(results: list[CaseResult]) -> dict[str, list[CaseResult]]:
    per_caso: dict[str, list[CaseResult]] = {}
    for result in results:
        per_caso.setdefault(result.case_id, []).append(result)
    return per_caso


@app.command()
def eval(
    only: str = typer.Option("", help="Esegui solo questi id, separati da virgola."),
    repeat: int = typer.Option(1, min=1, max=10, help="Ripetizioni per caso: misura la varianza."),
    cases: Path = _CASES_OPTION,
) -> None:
    """Esegue l'eval set con l'harness reale e stampa i risultati caso per caso.

    Costa: ogni caso è un run completo, con chiamate al modello e alla sandbox. Serve a sapere
    se i check discriminano e se il grader è rumoroso, prima di fidarsi del gate di promozione.

    Con `--repeat` ogni caso gira più volte. Un caso che passa 2 volte su 3 non è «passato»:
    è instabile, e distinguerlo da una regressione richiede più di un campione.
    """
    settings = Settings()
    results = asyncio.run(_run_eval(settings, only or None, cases, repeat))
    per_caso = _aggregate(results)

    table = Table(title=f"Eval baseline (repeat={repeat})")
    table.add_column("caso")
    table.add_column("check", justify="center")
    table.add_column("score", justify="right")
    table.add_column("grader", justify="right")
    table.add_column("token", justify="right")
    table.add_column("tempo", justify="right")
    for case_id, runs in per_caso.items():
        passati = sum(run.checks_passed for run in runs)
        if passati == len(runs):
            esito = "[green]✓[/green]" if repeat == 1 else f"[green]{passati}/{len(runs)}[/green]"
        elif passati == 0:
            esito = "[red]✗[/red]" if repeat == 1 else f"[red]{passati}/{len(runs)}[/red]"
        else:
            esito = f"[yellow]{passati}/{len(runs)} instabile[/yellow]"
        voti = [score for run in runs for score in run.grader_scores]
        grader = f"{mean(voti):.2f}" if voti else "—"
        table.add_row(
            case_id,
            esito,
            f"{mean([run.check_score for run in runs]):.2f}",
            grader,
            f"{sum(run.tokens for run in runs):,}",
            f"{sum(run.elapsed_ms for run in runs) / 1000:.1f}s",
        )
    console.print(table)

    summary = summarize(results)
    instabili = [
        cid
        for cid, runs in per_caso.items()
        if 0 < sum(r.checks_passed for r in runs) < len(runs)
    ]
    console.print(
        f"[bold]check pass rate[/bold] {summary.check_pass_rate:.0%} · "
        f"[bold]score medio[/bold] {summary.avg_check_score:.2f} · "
        f"[bold]completion[/bold] {summary.completion_rate:.0%} · "
        f"[bold]token[/bold] {summary.total_tokens:,} · "
        f"[bold]tempo[/bold] {summary.elapsed_ms / 1000:.0f}s"
    )
    if instabili:
        console.print(f"[yellow]casi instabili:[/yellow] {', '.join(instabili)}")
    visti: set[str] = set()
    for result in results:
        if result.check_failures and result.case_id not in visti:
            visti.add(result.case_id)
            console.print(f"[red]{result.case_id}[/red]: " + "; ".join(result.check_failures))
            if result.answer:
                testo = " ".join(result.answer.split())[:220]
                console.print(f"  [dim]risposta:[/dim] {testo}…")


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
