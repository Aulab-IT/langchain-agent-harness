"""Mantiene allineati i riferimenti del manuale comportamentale e il codice.

Il manuale in ``docs/handbook/`` cita il codice per file e riga (``runner.py · L186–197``).
I numeri di riga marciscono a ogni refactor, e marciscono in silenzio: un range che esiste
ancora ma nel frattempo contiene altro codice non fallisce nessun test, e il manuale mente.

Qui l'ancora smette di dire *dove* guardare e inizia a dire *cosa* ci si aspetta di trovare.
Per ogni ancora si registra un'impronta di contenuto — la riga più distintiva all'inizio del
range citato e quella alla fine — in ``docs/handbook/anchors.lock.json``. Il numero di riga
diventa un valore derivato: si ritrova l'impronta nel file e si ricalcola.

Tre modalità:

``--adopt``  registra le ancore nuove nel lockfile (bootstrap, o dopo aver scritto una pagina)
``--check``  verifica che ogni impronta sia dove il manuale dice; esce ≠0 se non lo è (CI)
``--write``  rilocalizza le impronte e riscrive i numeri nei ``.md``

Quattro esiti possibili per un'ancora. ``ok`` e ``relocated`` si risolvono da soli;
``ambiguous`` viene segnalato senza toccare niente; ``lost`` significa che quel codice non
esiste più — non è aritmetica da sistemare, è una pagina da riscrivere.

Limite dichiarato: lo strumento verifica il riferimento, non la verità. Sa dire che
``runner.py · L186–197`` contiene ancora quel blocco, non se la frase che lo descrive è
ancora corretta.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "docs" / "handbook"
LOCKFILE = HANDBOOK / "anchors.lock.json"

# I file citati per nome corto vivono qui, in ordine di preferenza.
SEARCH_ROOTS = (
    ROOT / "src" / "agent_harness",
    ROOT / "client" / "src",
    ROOT / "client" / "src" / "components" / "shared",
    ROOT,
)

_PATH = re.compile(r"(?<![\w/.-])(?P<path>[\w./-]+\.(?:py|tsx|ts))(?![\w.])")
_RANGE = re.compile(r"L(?P<a>\d+)(?:(?P<dash>[–-])(?P<b>\d+))?")

# Quante righe in testa e in coda al range sono candidate a fare da impronta. Poche: più ci
# si allontana dal bordo, più l'offset diventa fragile a modifiche interne al blocco.
_CANDIDATES = 3

Outcome = Literal["ok", "relocated", "ambiguous", "lost", "new"]


@dataclass(frozen=True)
class Anchor:
    """Una citazione `file · Lx–y` dentro un documento, con la sua posizione nel testo."""

    doc: Path
    file: Path
    start: int
    end: int
    dash: str
    span: tuple[int, int]  # posizione del token "Lx–y" nel testo del documento

    @property
    def key(self) -> str:
        rel_doc = self.doc.relative_to(ROOT).as_posix()
        rel_file = self.file.relative_to(ROOT).as_posix()
        return f"{rel_doc}|{rel_file}|{self.start}-{self.end}"

    def render(self, start: int, end: int) -> str:
        return f"L{start}" if start == end else f"L{start}{self.dash}{end}"


@dataclass(frozen=True)
class Fingerprint:
    """Cosa ci si aspetta di trovare ai due bordi del range, e a che distanza dal bordo."""

    head: str
    head_offset: int
    tail: str
    tail_offset: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "head_offset": self.head_offset,
            "tail": self.tail,
            "tail_offset": self.tail_offset,
        }


@dataclass
class Result:
    anchor: Anchor
    outcome: Outcome
    start: int
    end: int
    detail: str = ""


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def by_outcome(self, outcome: Outcome) -> list[Result]:
        return [r for r in self.results if r.outcome == outcome]

    @property
    def counts(self) -> Counter[str]:
        return Counter(r.outcome for r in self.results)


# --- lettura dei documenti ------------------------------------------------------------


def resolve_file(name: str) -> Path | None:
    for root in SEARCH_ROOTS:
        candidate = root / name
        if candidate.is_file():
            return candidate.resolve()
    return None


def parse_anchors(doc: Path) -> list[Anchor]:
    """Estrae le ancore di un documento, riga per riga.

    Un'ancora non attraversa mai una riga di markdown, e sulla stessa riga un percorso può
    essere seguito da più range (le tabelle di riepilogo scrivono
    ``| `durable.py` | L42, L207–224 |``). Si associa quindi ogni range al percorso che lo
    precede sulla stessa riga, fermandosi al percorso successivo.
    """
    anchors: list[Anchor] = []
    offset = 0
    for line in doc.read_text(encoding="utf-8").splitlines(keepends=True):
        paths = list(_PATH.finditer(line))
        for index, match in enumerate(paths):
            resolved = resolve_file(match.group("path"))
            if resolved is None:
                continue
            stop = paths[index + 1].start() if index + 1 < len(paths) else len(line)
            for rng in _RANGE.finditer(line, match.end(), stop):
                start = int(rng.group("a"))
                end = int(rng.group("b") or start)
                anchors.append(
                    Anchor(
                        doc=doc,
                        file=resolved,
                        start=start,
                        end=end,
                        dash=rng.group("dash") or "–",
                        span=(offset + rng.start(), offset + rng.end()),
                    )
                )
        offset += len(line)
    return anchors


def all_anchors() -> list[Anchor]:
    found: list[Anchor] = []
    for doc in sorted(HANDBOOK.rglob("*.md")):
        found.extend(parse_anchors(doc))
    return found


# --- impronte -------------------------------------------------------------------------


def _normalize(line: str) -> str:
    return " ".join(line.split())


def _distinctiveness(lines: list[str], text: str) -> int:
    """Quante volte una riga normalizzata compare nel file. Meno è, meglio ancora."""
    target = _normalize(text)
    return sum(1 for line in lines if _normalize(line) == target)


def _pick(lines: list[str], indexes: list[int]) -> int | None:
    """Sceglie fra le righe candidate la più distintiva, non semplicemente la prima.

    ``    return None`` compare ovunque e come impronta non vale niente; il commento che la
    precede identifica il punto in modo univoco. A parità di unicità si preferisce la riga
    più vicina al bordo, così l'offset resta piccolo. ``None`` se sono tutte vuote.
    """
    scored = [
        (_distinctiveness(lines, lines[i]), position, i)
        for position, i in enumerate(indexes)
        if _normalize(lines[i])
    ]
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    return scored[0][2]


def fingerprint(lines: list[str], anchor: Anchor) -> Fingerprint | None:
    """Impronta dei due bordi del range citato, con la distanza dal bordo.

    ``None`` quando il range non contiene niente di identificabile: fuori dal file, oppure
    fatto di sole righe vuote. Il secondo caso è quasi sempre un'ancora sbagliata di una
    riga — il tipo di errore che un controllo sui soli limiti non vede.
    """
    if anchor.start < 1 or anchor.end > len(lines) or anchor.start > anchor.end:
        return None

    head_pool = list(range(anchor.start - 1, min(anchor.start - 1 + _CANDIDATES, anchor.end)))
    head_index = _pick(lines, head_pool)
    if head_index is None:
        return None

    # La coda non può precedere la testa: su un range di due o tre righe i due insiemi di
    # candidate si sovrappongono, e senza questo vincolo l'impronta si incrocia.
    tail_pool = [
        i
        for i in range(anchor.end - 1, max(anchor.end - 1 - _CANDIDATES, anchor.start - 2), -1)
        if i >= head_index
    ]
    tail_index = _pick(lines, tail_pool)
    if tail_index is None:
        tail_index = head_index

    return Fingerprint(
        head=_normalize(lines[head_index]),
        head_offset=head_index - (anchor.start - 1),
        tail=_normalize(lines[tail_index]),
        tail_offset=(anchor.end - 1) - tail_index,
    )


# --- rilocalizzazione -----------------------------------------------------------------


def _matches(lines: list[str], text: str) -> list[int]:
    """Numeri di riga (1-based) in cui compare la riga normalizzata."""
    if not text:
        return []
    return [i + 1 for i, line in enumerate(lines) if _normalize(line) == text]


def _nearest(candidates: list[int], target: int) -> int:
    return min(candidates, key=lambda value: (abs(value - target), value))


def relocate(lines: list[str], anchor: Anchor, print_: Fingerprint) -> Result:
    """Ritrova l'impronta nel file. Il numero di riga è un risultato, non un input."""
    heads = _matches(lines, print_.head)
    tails = _matches(lines, print_.tail)
    if not heads or not tails:
        return Result(anchor, "lost", anchor.start, anchor.end, "impronta non più nel file")

    start = _nearest(heads, anchor.start + print_.head_offset) - print_.head_offset
    # `tail_offset` è quanto la fine del range sta DOPO la riga-impronta, quindi si somma.
    valid_tails = [t for t in tails if t + print_.tail_offset >= start]
    if not valid_tails:
        return Result(anchor, "ambiguous", anchor.start, anchor.end, "coda prima della testa")
    end = _nearest(valid_tails, anchor.end - print_.tail_offset) + print_.tail_offset

    # Ambiguità reale: più corrispondenze ugualmente vicine alla posizione precedente. Si
    # segnala invece di scegliere a caso — una riscrittura sbagliata è peggio di una mancata.
    for candidates, chosen, reference in (
        (heads, start + print_.head_offset, anchor.start + print_.head_offset),
        (valid_tails, end - print_.tail_offset, anchor.end - print_.tail_offset),
    ):
        distance = abs(chosen - reference)
        rivals = [c for c in candidates if c != chosen and abs(c - reference) == distance]
        if rivals:
            return Result(
                anchor, "ambiguous", anchor.start, anchor.end, "più corrispondenze equidistanti"
            )

    if (start, end) == (anchor.start, anchor.end):
        return Result(anchor, "ok", start, end)
    return Result(anchor, "relocated", start, end, f"L{anchor.start}–{anchor.end} → L{start}–{end}")


# --- lockfile -------------------------------------------------------------------------


def load_lock() -> dict[str, dict[str, Any]]:
    if not LOCKFILE.is_file():
        return {}
    data: dict[str, dict[str, Any]] = json.loads(LOCKFILE.read_text(encoding="utf-8"))
    return data


def save_lock(entries: dict[str, dict[str, Any]]) -> None:
    ordered = {key: entries[key] for key in sorted(entries)}
    LOCKFILE.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- esecuzione -----------------------------------------------------------------------


def run(mode: Literal["adopt", "check", "write"]) -> Report:
    lock = load_lock()
    report = Report()
    file_lines: dict[Path, list[str]] = {}
    fresh: dict[str, dict[str, Any]] = {}

    for anchor in all_anchors():
        if anchor.file not in file_lines:
            file_lines[anchor.file] = anchor.file.read_text(encoding="utf-8").splitlines()
        lines = file_lines[anchor.file]

        entry = lock.get(anchor.key)
        if entry is None:
            # Ancora mai vista: in adopt la si registra, altrove la si segnala e basta.
            print_ = fingerprint(lines, anchor)
            if print_ is None:
                detail = (
                    "range fuori dal file"
                    if anchor.end > len(lines)
                    else "il range citato è vuoto: ancora sbagliata, non codice sparito"
                )
                report.results.append(Result(anchor, "lost", anchor.start, anchor.end, detail))
                continue
            report.results.append(
                Result(anchor, "new", anchor.start, anchor.end, "non nel lockfile")
            )
            if mode == "adopt":
                fresh[anchor.key] = _entry(anchor, print_)
            continue

        print_ = Fingerprint(
            head=entry["head"],
            head_offset=int(entry["head_offset"]),
            tail=entry["tail"],
            tail_offset=int(entry["tail_offset"]),
        )
        result = relocate(lines, anchor, print_)
        report.results.append(result)

        if mode in ("adopt", "write") and result.outcome in ("ok", "relocated"):
            moved = Anchor(
                doc=anchor.doc,
                file=anchor.file,
                start=result.start,
                end=result.end,
                dash=anchor.dash,
                span=anchor.span,
            )
            fresh[moved.key] = _entry(moved, print_)
        elif mode in ("adopt", "write"):
            fresh[anchor.key] = entry

    if mode == "write":
        rewrite_docs(report)
    if mode in ("adopt", "write"):
        save_lock(fresh)

    return report


def _entry(anchor: Anchor, print_: Fingerprint) -> dict[str, Any]:
    return {
        "doc": anchor.doc.relative_to(ROOT).as_posix(),
        "file": anchor.file.relative_to(ROOT).as_posix(),
        **print_.to_dict(),
        "last_seen": [anchor.start, anchor.end],
    }


def rewrite_docs(report: Report) -> None:
    """Riscrive i token `Lx–y` spostati, un documento alla volta.

    Le sostituzioni si applicano dal fondo del testo verso l'inizio: così gli offset delle
    ancore precedenti restano validi mentre la lunghezza del testo cambia.
    """
    moved = report.by_outcome("relocated")
    by_doc: dict[Path, list[Result]] = {}
    for result in moved:
        by_doc.setdefault(result.anchor.doc, []).append(result)

    for doc, results in by_doc.items():
        text = doc.read_text(encoding="utf-8")
        for result in sorted(results, key=lambda r: r.anchor.span[0], reverse=True):
            begin, finish = result.anchor.span
            text = text[:begin] + result.anchor.render(result.start, result.end) + text[finish:]
        doc.write_text(text, encoding="utf-8")


# --- interfaccia ----------------------------------------------------------------------


def summarize(report: Report, mode: str) -> int:
    counts = report.counts
    total = sum(counts.values())
    print(f"{total} ancore · " + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

    for outcome, title in (
        ("lost", "EVIDENZA SPARITA — la pagina va riscritta"),
        ("ambiguous", "AMBIGUE — non toccate, servono occhi umani"),
        ("relocated", "SPOSTATE"),
        ("new", "NON NEL LOCKFILE — servono --adopt"),
    ):
        items = report.by_outcome(outcome)  # type: ignore[arg-type]
        if not items:
            continue
        print(f"\n{title}")
        for result in items[:40]:
            doc = result.anchor.doc.relative_to(HANDBOOK).as_posix()
            file = result.anchor.file.name
            detail = f"  {result.detail}" if result.detail else ""
            print(f"  {doc}  {file} L{result.anchor.start}–{result.anchor.end}{detail}")
        if len(items) > 40:
            print(f"  … e altre {len(items) - 40}")

    if mode == "check":
        blocking = len(report.by_outcome("lost")) + len(report.by_outcome("ambiguous"))
        blocking += len(report.by_outcome("relocated")) + len(report.by_outcome("new"))
        if blocking:
            print("\nIl manuale non è allineato al codice. `make handbook` per rigenerare.")
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--adopt", action="store_true", help="registra le ancore nuove")
    group.add_argument("--check", action="store_true", help="verifica senza modificare (CI)")
    group.add_argument("--write", action="store_true", help="rilocalizza e riscrive i .md")
    args = parser.parse_args()

    mode = "adopt" if args.adopt else "check" if args.check else "write"
    return summarize(run(mode), mode)


if __name__ == "__main__":
    sys.exit(main())
