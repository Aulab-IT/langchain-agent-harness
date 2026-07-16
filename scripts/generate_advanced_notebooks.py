"""Genera la mini-serie avanzata 07-12, composta solo da celle standard-library."""

# ruff: noqa: E501, RUF001

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks"


def md(text: str) -> nbformat.NotebookNode:
    return nbformat.v4.new_markdown_cell(dedent(text).strip())


def code(text: str) -> nbformat.NotebookNode:
    return nbformat.v4.new_code_cell(dedent(text).strip())


def write(name: str, cells: list[nbformat.NotebookNode]) -> None:
    notebook = nbformat.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.11"},
        },
    )
    nbformat.write(notebook, OUT / name)


def providers() -> None:
    write(
        "07_provider_capability_e_costi.ipynb",
        [
            md(
                """
                # 07 · Provider, capability e costi

                Mini-harness provider-neutral. Solo Python standard library: nessuna API, chiave o
                import dal progetto. Costruiamo contratti, preflight, costo e tassonomia errori.
                """
            ),
            md(
                """
                ## 1 · Descrivere capacità, non indovinarle

                Un nome modello non garantisce tool, structured output o caching. Le capacità sono
                dati espliciti usati prima del run.
                """
            ),
            code(
                """
                from dataclasses import dataclass
                from decimal import Decimal

                @dataclass(frozen=True)
                class Capabilities:
                    context_window: int
                    tools: bool
                    structured_output: bool
                    parallel_tools: bool

                @dataclass(frozen=True)
                class Model:
                    provider: str
                    name: str
                    capabilities: Capabilities
                    input_per_million: Decimal
                    output_per_million: Decimal

                cloud = Model("cloud", "smart", Capabilities(128_000, True, True, True), Decimal("1"), Decimal("6"))
                local = Model("local", "small", Capabilities(8_192, True, False, False), Decimal("0"), Decimal("0"))
                """
            ),
            md("## 2 · Capability gate prima del lavoro"),
            code(
                """
                def preflight(model: Model, *, needs_structured: bool, input_tokens: int) -> None:
                    if input_tokens >= model.capabilities.context_window:
                        raise ValueError("context_length")
                    if needs_structured and not model.capabilities.structured_output:
                        raise ValueError("unsupported_structured_output")

                preflight(cloud, needs_structured=True, input_tokens=2_000)
                try:
                    preflight(local, needs_structured=True, input_tokens=2_000)
                except ValueError as error:
                    print("Rifiuto anticipato:", error)
                """
            ),
            md("## 3 · Usage normalizzato e costo confrontabile"),
            code(
                """
                def cost(model: Model, input_tokens: int, output_tokens: int) -> Decimal:
                    million = Decimal(1_000_000)
                    return (Decimal(input_tokens) * model.input_per_million + Decimal(output_tokens) * model.output_per_million) / million

                for candidate in (cloud, local):
                    print(candidate.provider, cost(candidate, 10_000, 2_000))
                """
            ),
            md("## 4 · Errori vendor-specifici → decisioni comuni"),
            code(
                """
                def classify_error(message: str) -> tuple[str, bool]:
                    text = message.casefold()
                    if "429" in text or "rate limit" in text:
                        return "rate_limit", True
                    if "timeout" in text:
                        return "timeout", True
                    if "401" in text or "api key" in text:
                        return "auth", False
                    if "context" in text:
                        return "context_length", False
                    return "unknown", False

                assert classify_error("HTTP 429 rate limit") == ("rate_limit", True)
                assert classify_error("401 invalid API key") == ("auth", False)
                print("Tassonomia verificata")
                """
            ),
            md(
                """
                ## Prova tu

                Aggiungi un provider con tool ma senza tool paralleli. Fai fallire il preflight solo
                quando il piano contiene due chiamate indipendenti da eseguire insieme.
                """
            ),
        ],
    )


def context_budget() -> None:
    write(
        "08_budget_contesto_e_run.ipynb",
        [
            md(
                """
                # 08 · Budget del contesto e del run

                Due budget: finestra corrente del modello e consumo cumulativo del run. Notebook
                offline, autocontenuto, solo standard library.
                """
            ),
            md("## 1 · Misurare categorie del contesto"),
            code(
                """
                from dataclasses import dataclass
                from decimal import Decimal
                from hashlib import sha256
                from pathlib import Path
                from tempfile import TemporaryDirectory

                @dataclass
                class Message:
                    kind: str
                    text: str
                    reconstructible: bool = False

                def tokens(text: str) -> int:
                    return max(1, len(text) // 4)

                messages = [Message("system", "regole " * 100), Message("tool", "X" * 8_000, True)]
                total = sum(tokens(item.text) for item in messages)
                reconstructible = sum(tokens(item.text) for item in messages if item.reconstructible)
                print({"total": total, "reconstructible": reconstructible})
                """
            ),
            md("## 2 · Decidere: keep, offload, compact, stop"),
            code(
                """
                def decide(total: int, usable: int, reconstructible: int) -> str:
                    ratio = total / usable
                    if ratio >= 1:
                        return "stop"
                    if ratio >= 0.75 and reconstructible > 500:
                        return "offload"
                    if ratio >= 0.75:
                        return "compact"
                    return "keep"

                action = decide(total, usable=2_400, reconstructible=reconstructible)
                print("Azione:", action)
                assert action == "offload"
                """
            ),
            md("## 3 · Offload recuperabile: file + checksum + estratto"),
            code(
                """
                with TemporaryDirectory() as temporary:
                    target = Path(temporary) / "tool-output.txt"
                    full = messages[-1].text
                    target.write_text(full, encoding="utf-8")
                    digest = sha256(full.encode()).hexdigest()[:16]
                    replacement = f"[offloaded] ref={target} sha256={digest} excerpt={full[:80]}…"
                    assert sha256(target.read_bytes()).hexdigest().startswith(digest)
                    print(replacement)
                """
            ),
            md("## 4 · Prenotare budget prima della chiamata"),
            code(
                """
                @dataclass
                class Ledger:
                    max_tokens: int
                    max_cost: Decimal
                    used_tokens: int = 0
                    used_cost: Decimal = Decimal(0)

                    def reserve(self, input_tokens: int, output_tokens: int, rate_in: Decimal, rate_out: Decimal):
                        projected_tokens = self.used_tokens + input_tokens + output_tokens
                        projected_cost = self.used_cost + (Decimal(input_tokens) * rate_in + Decimal(output_tokens) * rate_out) / Decimal(1_000_000)
                        if projected_tokens > self.max_tokens or projected_cost > self.max_cost:
                            raise RuntimeError("budget_exceeded")
                        return input_tokens, output_tokens, projected_cost - self.used_cost

                    def settle(self, reservation, actual_input: int, actual_output: int, rate_in: Decimal, rate_out: Decimal):
                        self.used_tokens += actual_input + actual_output
                        self.used_cost += (Decimal(actual_input) * rate_in + Decimal(actual_output) * rate_out) / Decimal(1_000_000)

                ledger = Ledger(10_000, Decimal("0.10"))
                reservation = ledger.reserve(2_000, 1_000, Decimal("1"), Decimal("6"))
                ledger.settle(reservation, 2_000, 300, Decimal("1"), Decimal("6"))
                print(ledger)
                """
            ),
            md("## Prova tu\n\nSimula due prenotazioni parallele: entrambe devono considerare il budget già riservato, non solo quello consumato."),
        ],
    )


def durable() -> None:
    write(
        "09_esecuzione_durevole_e_hitl.ipynb",
        [
            md(
                """
                # 09 · Esecuzione durevole e HITL

                Coda SQLite minimale con idempotenza, lease e interrupt persistenti. Un restart viene
                simulato chiudendo e riaprendo la connessione.
                """
            ),
            md("## 1 · Schema e stati terminali espliciti"),
            code(
                """
                import json, sqlite3, uuid
                from pathlib import Path
                from tempfile import TemporaryDirectory

                TERMINAL = {"completed", "incomplete", "failed_verification", "budget_exceeded", "security_stop"}

                def open_store(path: Path):
                    db = sqlite3.connect(path)
                    db.row_factory = sqlite3.Row
                    db.executescript('''
                    CREATE TABLE IF NOT EXISTS work (
                        id TEXT PRIMARY KEY, idem TEXT UNIQUE, state TEXT, owner TEXT, version INTEGER, payload TEXT
                    );
                    CREATE TABLE IF NOT EXISTS interrupts (
                        id TEXT PRIMARY KEY, run_id TEXT, status TEXT, payload TEXT, resolution TEXT
                    );
                    ''')
                    return db
                """
            ),
            md("## 2 · Enqueue idempotente e claim con lease logico"),
            code(
                """
                def enqueue(db, idem: str, payload: dict) -> str:
                    existing = db.execute("SELECT id FROM work WHERE idem=?", (idem,)).fetchone()
                    if existing:
                        return existing["id"]
                    run_id = str(uuid.uuid4())
                    db.execute("INSERT INTO work VALUES (?, ?, 'queued', NULL, 0, ?)", (run_id, idem, json.dumps(payload)))
                    db.commit()
                    return run_id

                def claim(db, owner: str):
                    row = db.execute("SELECT * FROM work WHERE state='queued' LIMIT 1").fetchone()
                    if not row:
                        return None
                    db.execute("UPDATE work SET state='running', owner=?, version=version+1 WHERE id=? AND version=?", (owner, row["id"], row["version"]))
                    db.commit()
                    return db.execute("SELECT * FROM work WHERE id=?", (row["id"],)).fetchone()
                """
            ),
            md("## 3 · Interrupt persistente, poi restart"),
            code(
                """
                with TemporaryDirectory() as temporary:
                    path = Path(temporary) / "runs.sqlite"
                    db = open_store(path)
                    one = enqueue(db, "session:request-1", {"goal": "crea report"})
                    two = enqueue(db, "session:request-1", {"goal": "duplicato"})
                    assert one == two
                    item = claim(db, "worker-a")
                    interrupt_id = str(uuid.uuid4())
                    db.execute("INSERT INTO interrupts VALUES (?, ?, 'pending', ?, NULL)", (interrupt_id, item["id"], json.dumps({"command": "[redacted]"})))
                    db.commit(); db.close()

                    db = open_store(path)  # restart
                    pending = db.execute("SELECT * FROM interrupts WHERE status='pending'").fetchone()
                    assert pending["id"] == interrupt_id
                    db.execute("UPDATE interrupts SET status='resolved', resolution=? WHERE id=? AND status='pending'", (json.dumps({"decision": "approve"}), interrupt_id))
                    db.execute("UPDATE work SET state='completed', version=version+1 WHERE id=?", (item["id"],))
                    db.commit()
                    print(dict(db.execute("SELECT id, state, version FROM work").fetchone()))
                    db.close()
                """
            ),
            md(
                """
                ## Perché non basta

                SQLite rende durevole orchestrazione, non effetti esterni. Un provider email o deploy
                deve accettare la stessa chiave idempotente; altrimenti un retry può duplicare l’effetto.
                """
            ),
            md("## Prova tu\n\nAggiungi `lease_until`; rendi reclamabile un item `running` solo dopo scadenza."),
        ],
    )


def subagents() -> None:
    write(
        "10_governance_subagenti.ipynb",
        [
            md(
                """
                # 10 · Governance dei subagenti

                Router propone un piano; validatore deterministico applica least privilege, dipendenze,
                reviewer indipendente e budget. Solo standard library.
                """
            ),
            md("## 1 · Profili e task sono contratti"),
            code(
                """
                from dataclasses import dataclass, field

                @dataclass(frozen=True)
                class Profile:
                    name: str
                    capabilities: set[str]
                    tools: set[str]
                    read_only: bool

                @dataclass
                class Task:
                    id: str
                    agent: str
                    alternatives: list[str]
                    capabilities: set[str]
                    tools: set[str]
                    writes: bool
                    kind: str = "work"
                    depends_on: list[str] = field(default_factory=list)

                roster = {
                    "researcher": Profile("researcher", {"research"}, {"browser"}, True),
                    "builder": Profile("builder", {"python"}, {"sandbox"}, False),
                    "reviewer": Profile("reviewer", {"review"}, set(), True),
                }
                """
            ),
            md("## 2 · Validare capability, tool e scrittura"),
            code(
                """
                def supports(profile: Profile, task: Task) -> bool:
                    return task.capabilities <= profile.capabilities and task.tools <= profile.tools and not (task.writes and profile.read_only)

                def assign(task: Task) -> Task | None:
                    for name in [task.agent, *task.alternatives]:
                        if name in roster and supports(roster[name], task):
                            task.agent = name
                            return task
                    return None

                task = Task("build", "researcher", ["builder"], {"python"}, {"sandbox"}, True)
                validated = assign(task)
                assert validated and validated.agent == "builder"
                print("Assegnato a:", validated.agent)
                """
            ),
            md("## 3 · Bloccare cicli e review non indipendenti"),
            code(
                """
                def has_cycle(tasks: list[Task]) -> bool:
                    graph = {task.id: task.depends_on for task in tasks}
                    visiting, done = set(), set()
                    def visit(node):
                        if node in visiting: return True
                        if node in done: return False
                        visiting.add(node)
                        if any(visit(dep) for dep in graph.get(node, [])): return True
                        visiting.remove(node); done.add(node)
                        return False
                    return any(visit(node) for node in graph)

                cycle = [Task("a", "builder", [], set(), set(), False, depends_on=["b"]), Task("b", "builder", [], set(), set(), False, depends_on=["a"])]
                assert has_cycle(cycle)

                review = Task("review", "builder", ["reviewer"], {"review"}, set(), False, kind="review", depends_on=["build"])
                review = assign(review)
                assert review and review.agent == "reviewer" and review.agent != validated.agent
                print("Reviewer indipendente:", review.agent)
                """
            ),
            md("## 4 · Protocollo di risultato"),
            code(
                """
                def terminal_report(status: str, evidence: list[str], artifacts: list[str]) -> dict:
                    if status == "complete" and not evidence:
                        raise ValueError("complete richiede evidenza")
                    return {"status": status, "evidence": evidence, "artifacts": artifacts}

                report = terminal_report("complete", ["pytest: 12 passed"], ["report.md"])
                print(report)
                """
            ),
            md("## Prova tu\n\nAggiungi budget per agente e impedisci una seconda invocazione quando il residuo non copre la risposta finale."),
        ],
    )


def evidence() -> None:
    write(
        "11_manifest_e_delivery_gate.ipynb",
        [
            md(
                """
                # 11 · Manifest di evidenza e delivery gate

                Hash canonici, artefatti, snapshot read-only e autorizzazione separata. Notebook
                autocontenuto, offline, standard library.
                """
            ),
            md("## 1 · Manifest canonico"),
            code(
                """
                import hashlib, json, shutil, stat
                from pathlib import Path
                from tempfile import TemporaryDirectory

                def digest_bytes(value: bytes) -> str:
                    return hashlib.sha256(value).hexdigest()

                def canonical(value: dict) -> bytes:
                    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

                def build_manifest(goal: str, answer: str, workspace: Path, artifacts: list[str]) -> dict:
                    manifest = {
                        "goal_sha256": digest_bytes(goal.encode()),
                        "answer_sha256": digest_bytes(answer.encode()),
                        "artifacts": [{"path": name, "sha256": digest_bytes((workspace / name).read_bytes())} for name in artifacts],
                        "terminal_status": "completed",
                    }
                    manifest["manifest_sha256"] = digest_bytes(canonical(manifest))
                    return manifest
                """
            ),
            md("## 2 · Verifica e rilevamento manomissione"),
            code(
                """
                def verify(manifest: dict, workspace: Path) -> bool:
                    payload = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
                    if digest_bytes(canonical(payload)) != manifest["manifest_sha256"]:
                        return False
                    return all((workspace / item["path"]).is_file() and digest_bytes((workspace / item["path"]).read_bytes()) == item["sha256"] for item in manifest["artifacts"])

                with TemporaryDirectory() as temporary:
                    root = Path(temporary); workspace = root / "workspace"; workspace.mkdir()
                    (workspace / "report.txt").write_text("verificato", encoding="utf-8")
                    manifest = build_manifest("crea report", "fatto", workspace, ["report.txt"])
                    assert verify(manifest, workspace)
                    (workspace / "report.txt").write_text("alterato", encoding="utf-8")
                    assert not verify(manifest, workspace)
                    print("Tampering rilevato")
                """
            ),
            md("## 3 · Checker su snapshot separato"),
            code(
                """
                with TemporaryDirectory() as temporary:
                    root = Path(temporary); workspace = root / "workspace"; bundle = root / "bundle"
                    workspace.mkdir(); bundle.mkdir()
                    artifact = workspace / "report.txt"; artifact.write_text("versione approvata")
                    manifest = build_manifest("crea report", "fatto", workspace, ["report.txt"])
                    shutil.copy2(artifact, bundle / "report.txt")
                    (bundle / "report.txt").chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                    snapshot_ok = digest_bytes((bundle / "report.txt").read_bytes()) == manifest["artifacts"][0]["sha256"]
                    artifact.write_text("nuova versione")
                    assert snapshot_ok and not verify(manifest, workspace)
                    print("Checker separato:", snapshot_ok)
                """
            ),
            md("## 4 · Successo tecnico ≠ permesso di deploy"),
            code(
                """
                def delivery_ready(*, integrity, checker, branch, clean, ci, preview, rollback, approved):
                    return all([integrity, checker, branch not in {"main", "master", ""}, clean, ci, preview, rollback, approved])

                assert not delivery_ready(integrity=True, checker=True, branch="feature/x", clean=True, ci=False, preview=False, rollback=True, approved=True)
                assert delivery_ready(integrity=True, checker=True, branch="feature/x", clean=True, ci=True, preview=True, rollback=True, approved=True)
                print("Gate verificato")
                """
            ),
            md("## Prova tu\n\nLega approvazione a `manifest_sha256`; una modifica deve invalidarla automaticamente."),
        ],
    )


def evaluation() -> None:
    write(
        "12_eval_canary_e_rollback.ipynb",
        [
            md(
                """
                # 12 · Eval, canary e rollback

                Ultimo loop: confrontare baseline/candidato, bloccare regressioni, distribuire canary
                stabile e conservare rollback. Solo standard library, nessuna chiamata modello.
                """
            ),
            md("## 1 · Casi verificabili e confronto paired"),
            code(
                """
                from dataclasses import dataclass
                from hashlib import sha256
                from statistics import mean

                @dataclass(frozen=True)
                class Result:
                    case: str
                    passed: bool
                    tokens: int
                    latency_ms: int

                baseline = [Result("a", True, 100, 120), Result("b", False, 150, 200), Result("c", True, 120, 150)]
                candidate = [Result("a", True, 90, 110), Result("b", True, 140, 180), Result("c", True, 100, 140)]

                def summary(results):
                    return {"pass_rate": mean(item.passed for item in results), "tokens": sum(item.tokens for item in results), "latency": mean(item.latency_ms for item in results)}

                print("baseline", summary(baseline)); print("candidate", summary(candidate))
                """
            ),
            md("## 2 · Regression gate deterministico"),
            code(
                """
                def gate(base, cand) -> dict:
                    b, c = summary(base), summary(cand)
                    regressions = [left.case for left, right in zip(base, cand) if left.passed and not right.passed]
                    passed = not regressions and c["pass_rate"] >= b["pass_rate"] and c["tokens"] <= b["tokens"] * 1.2 and c["latency"] <= b["latency"] * 1.3
                    return {"passed": passed, "regressions": regressions, "token_ratio": c["tokens"] / b["tokens"]}

                decision = gate(baseline, candidate)
                assert decision["passed"]
                print(decision)
                """
            ),
            md("## 3 · Canary stabile per sessione"),
            code(
                """
                def arm(session_id: str, fraction: float) -> str:
                    bucket = int(sha256(session_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
                    return "canary" if bucket < fraction else "baseline"

                first = arm("session-42", 0.2)
                assert all(arm("session-42", 0.2) == first for _ in range(10))
                counts = {name: sum(arm(f"s-{i}", 0.2) == name for i in range(1_000)) for name in ("baseline", "canary")}
                print(counts)
                """
            ),
            md("## 4 · Versione attiva e rollback append-only"),
            code(
                """
                history = []
                active = {"max_tool_calls": 12}

                def promote(candidate_config: dict):
                    global active
                    history.append({"event": "before_promotion", "config": active.copy()})
                    active = candidate_config.copy()
                    history.append({"event": "promoted", "config": active.copy()})

                def rollback(version: dict):
                    global active
                    history.append({"event": "before_rollback", "config": active.copy()})
                    active = version.copy()

                promote({"max_tool_calls": 16})
                rollback(history[0]["config"])
                assert active == {"max_tool_calls": 12}
                print(history)
                """
            ),
            md(
                """
                ## Regola finale

                Il sistema che propone non cambia rubric o soglia con cui viene giudicato: altrimenti
                può aumentare il pass rate abbassando l’esame, non migliorando l’agente.
                """
            ),
            md("## Prova tu\n\nAggiungi gate live: servono almeno cinque run per arm e non-inferiorità su qualità, token e latenza."),
        ],
    )


def main() -> None:
    providers()
    context_budget()
    durable()
    subagents()
    evidence()
    evaluation()
    from enrich_notebooks import enrich

    for path in sorted(OUT.glob("0[7-9]_*.ipynb")) + sorted(OUT.glob("1[0-2]_*.ipynb")):
        enrich(path)
    print("Generati notebook avanzati 07-12.")


if __name__ == "__main__":
    main()
