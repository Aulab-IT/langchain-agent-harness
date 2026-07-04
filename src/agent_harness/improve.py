from __future__ import annotations

import json
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

# Solo queste chiavi possono essere applicate automaticamente: il resto della config
# resta sotto controllo umano diretto nel codice.
OVERRIDE_WHITELIST = frozenset(
    {"system_prompt_addendum", "harness_max_tool_calls", "harness_rubric_threshold"}
)


@dataclass
class Report:
    total_runs: int = 0
    failed_runs: int = 0
    grader_graded: int = 0
    grader_passed: int = 0
    grader_score_sum: float = 0.0
    tool_errors: Counter[str] = field(default_factory=Counter)
    slow_tools: Counter[str] = field(default_factory=Counter)

    @property
    def grader_pass_rate(self) -> float:
        return round(self.grader_passed / self.grader_graded, 3) if self.grader_graded else 0.0

    @property
    def grader_avg_score(self) -> float:
        return round(self.grader_score_sum / self.grader_graded, 3) if self.grader_graded else 0.0


class Proposal(BaseModel):
    """Proposta di miglioramento della config dell'harness.

    I campi override sono espliciti (whitelist strutturale): così lo schema è chiuso e
    compatibile con lo structured output stretto di OpenAI, e nessuna chiave arbitraria può
    finire nella config.
    """

    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    system_prompt_addendum: str | None = None
    harness_max_tool_calls: int | None = None
    harness_rubric_threshold: float | None = None

    @property
    def overrides(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.system_prompt_addendum:
            result["system_prompt_addendum"] = self.system_prompt_addendum
        if self.harness_max_tool_calls is not None:
            result["harness_max_tool_calls"] = self.harness_max_tool_calls
        if self.harness_rubric_threshold is not None:
            result["harness_rubric_threshold"] = self.harness_rubric_threshold
        return result


def build_report(events: list[dict[str, Any]], audit_lines: list[str]) -> Report:
    """Aggrega segnali dai trace persistiti (eventi + audit JSONL). Funzione pura."""
    report = Report()
    for event in events:
        etype = event.get("type", "")
        payload = event.get("payload", {}) or {}
        if etype == "run.completed":
            report.total_runs += 1
        elif etype == "run.failed":
            report.total_runs += 1
            report.failed_runs += 1
        elif etype == "grader.completed":
            report.grader_graded += 1
            if payload.get("passed"):
                report.grader_passed += 1
            report.grader_score_sum += float(payload.get("score", 0.0) or 0.0)
    for line in audit_lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        tool = str(record.get("tool", "?"))
        if record.get("status") == "error":
            report.tool_errors[tool] += 1
        if int(record.get("elapsed_ms", 0)) > 10_000:
            report.slow_tools[tool] += 1
    return report


def render_report(report: Report) -> str:
    return "\n".join(
        [
            f"Run totali: {report.total_runs}",
            f"Run falliti: {report.failed_runs}",
            f"Verifiche grader: {report.grader_graded} "
            f"(pass rate {report.grader_pass_rate}, score medio {report.grader_avg_score})",
            f"Errori tool: {dict(report.tool_errors)}",
            f"Tool lenti (>10s): {dict(report.slow_tools)}",
        ]
    )


async def propose(report_text: str, judge: Runnable[Any, Any]) -> Proposal:
    """Chiede all'agente d'analisi una proposta strutturata, filtrata sulla whitelist."""
    messages = [
        {
            "role": "system",
            "content": (
                "Sei un ingegnere che migliora la configurazione di un agent harness. "
                "Analizza il REPORT dei trace di produzione e proponi modifiche mirate. "
                "Compila `summary` e `findings`. Proponi override solo se giustificati dal report, "
                "lasciando null gli altri: `system_prompt_addendum` (testo da aggiungere al prompt "
                "di sistema), `harness_max_tool_calls` (intero), `harness_rubric_threshold` "
                "(float 0-1). Non inventare metriche: basati solo sul report."
            ),
        },
        {"role": "user", "content": f"REPORT:\n{report_text}"},
    ]
    proposal: Proposal = await judge.ainvoke(messages)
    return proposal


def write_proposal(proposal: Proposal, report_text: str, improvements_dir: Path) -> Path:
    improvements_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = improvements_dir / f"{stamp}.md"
    findings = "\n".join(f"- {item}" for item in proposal.findings) or "- (nessuno)"
    overrides = json.dumps(proposal.overrides, ensure_ascii=False, indent=2)
    path.write_text(
        f"# Proposta di miglioramento {stamp}\n\n"
        f"## Sintesi\n{proposal.summary or '(vuota)'}\n\n"
        f"## Report trace\n```\n{report_text}\n```\n\n"
        f"## Osservazioni\n{findings}\n\n"
        f"## Override proposti (whitelist)\n```json\n{overrides}\n```\n\n"
        "> Propose-only: applica con `harness improve --apply` dopo revisione umana.\n",
        encoding="utf-8",
    )
    # Sidecar leggibile a macchina: consente di applicare una proposta salvata dopo revisione.
    path.with_suffix(".overrides.json").write_text(
        json.dumps(proposal.overrides, ensure_ascii=False), encoding="utf-8"
    )
    return path


def saved_overrides(proposal_path: Path) -> dict[str, Any]:
    """Legge gli override whitelisted associati a una proposta salvata."""
    sidecar = proposal_path.with_suffix(".overrides.json")
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {key: value for key, value in data.items() if key in OVERRIDE_WHITELIST}


def _dump_toml(values: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in values.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, str):
            lines.append(f"{key} = {json.dumps(value)}")  # stringa TOML basic valida
        else:
            lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"


def apply_override_values(values: dict[str, Any], overrides_path: Path) -> dict[str, Any]:
    """Applica valori whitelisted a un file TOML fuori dal codice (reversibile)."""
    current: dict[str, Any] = {}
    if overrides_path.exists():
        current = tomllib.loads(overrides_path.read_text(encoding="utf-8"))
    for key, value in values.items():
        if key in OVERRIDE_WHITELIST:
            current[key] = value
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(_dump_toml(current), encoding="utf-8")
    return current


def apply_overrides(proposal: Proposal, overrides_path: Path) -> dict[str, Any]:
    """Applica gli override di una proposta appena generata."""
    return apply_override_values(proposal.overrides, overrides_path)


def load_overrides(overrides_path: Path) -> dict[str, Any]:
    """Legge gli override applicati; usato dalla factory per chiudere il loop."""
    if not overrides_path.exists():
        return {}
    data = tomllib.loads(overrides_path.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if key in OVERRIDE_WHITELIST}


async def run_improvement(
    settings: Any, *, since: int = 1_000, apply: bool = False
) -> dict[str, Any]:
    """Orchestrazione hill-climbing: raccoglie trace, propone, salva; applica solo se richiesto."""
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    from agent_harness.control_store import ControlStore

    store = ControlStore(settings)
    try:
        events = store.recent_events(limit=since)
    finally:
        store.close()
    audit_path = settings.state_dir / "audit.jsonl"
    audit_lines = audit_path.read_text(encoding="utf-8").splitlines() if audit_path.exists() else []

    report = build_report(events, audit_lines)
    report_text = render_report(report)

    api_key = settings.require_openai_key()
    model = ChatOpenAI(
        model=settings.openai_strong_model,
        api_key=SecretStr(api_key),
        reasoning_effort="medium",
        use_responses_api=True,
        store=False,
        timeout=120,
    )
    proposal = await propose(report_text, model.with_structured_output(Proposal))

    improvements_dir = settings.state_dir / "improvements"
    path = write_proposal(proposal, report_text, improvements_dir)
    applied: dict[str, Any] = {}
    if apply:
        applied = apply_overrides(proposal, settings.state_dir / "harness_overrides.toml")
    return {
        "path": path,
        "summary": proposal.summary,
        "overrides": proposal.overrides,
        "applied": applied,
        "report": report_text,
    }
