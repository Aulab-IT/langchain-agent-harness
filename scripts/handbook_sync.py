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
import functools
import json
import re
import sys
import tomllib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

_RANGE = re.compile(r"L(?P<a>\d+)(?:(?P<dash>[–-])(?P<b>\d+))?")

# Quante righe in testa e in coda al range sono candidate a fare da impronta. Poche: più ci
# si allontana dal bordo, più l'offset diventa fragile a modifiche interne al blocco.
_CANDIDATES = 3

Outcome = Literal["ok", "relocated", "ambiguous", "lost", "new"]

_DEFAULTS: dict[str, Any] = {
    "handbook": "docs/handbook",
    "lockfile": "docs/handbook/anchors.lock.json",
    "search_roots": ["."],
    "extensions": ["py"],
    "project": "",
}


# --- configurazione -------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Dove sta il manuale e dove si risolvono i file che cita.

    `search_roots` è la parte che non si può indovinare: è una lista **ordinata di
    preferenza** che decide quale file vince quando un'ancora usa il nome corto
    (`runner.py`). Su un repo con `client/src/index.ts` e `server/src/index.ts` l'ordine è
    l'unica cosa che distingue lo snippet giusto da uno sbagliato ma plausibile. Per questo
    vive in un file versionato insieme al manuale, non in un flag da ripetere in Makefile,
    CI, test e skill.
    """

    root: Path
    handbook: Path
    lockfile: Path
    search_roots: tuple[Path, ...]
    extensions: tuple[str, ...]
    html_out: Path
    html_context_lines: int
    html_editor: str
    # Come si chiama il progetto negli artefatti generati. Configurato, non dedotto dal
    # nome della cartella: una CI che clona in una directory con un altro nome — il nome
    # del repository, di solito — produrrebbe un artefatto diverso da quello versionato,
    # e il gate fallirebbe senza che nessuno abbia toccato il manuale.
    project: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, Any], root: Path) -> Config:
        merged = {**_DEFAULTS, **data}
        html = dict(data.get("html") or {})
        return cls(
            root=root,
            handbook=root / str(merged["handbook"]),
            lockfile=root / str(merged["lockfile"]),
            search_roots=tuple(root / str(item) for item in merged["search_roots"]),
            extensions=tuple(str(item).lstrip(".") for item in merged["extensions"]),
            html_out=root / str(html.get("out", "build/handbook/index.html")),
            html_context_lines=int(html.get("context_lines", 3)),
            html_editor=str(html.get("editor", "vscode")),
            project=str(merged["project"]),
        )

    @classmethod
    def load(cls, path: Path) -> Config:
        """Legge `[tool.handbook]` da un pyproject.toml, o la radice di un handbook.toml."""
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if path.name == "pyproject.toml":
            data = data.get("tool", {}).get("handbook", {})
        return cls.from_mapping(data, path.parent)

    @classmethod
    def discover(cls, start: Path | None = None) -> Config:
        """Risale dalla cartella corrente cercando una configurazione.

        Ordine: `pyproject.toml` con `[tool.handbook]`, poi `handbook.toml`. La radice del
        progetto è la cartella del file trovato, non il cwd: così i comandi funzionano da
        qualunque sottocartella.
        """
        current = (start or Path.cwd()).resolve()
        for folder in [current, *current.parents]:
            pyproject = folder / "pyproject.toml"
            if pyproject.is_file():
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                if "handbook" in data.get("tool", {}):
                    return cls.from_mapping(data["tool"]["handbook"], folder)
            handbook_toml = folder / "handbook.toml"
            if handbook_toml.is_file():
                return cls.load(handbook_toml)
        raise SystemExit(
            "Nessuna configurazione trovata: serve [tool.handbook] in pyproject.toml "
            "oppure un handbook.toml. Con la skill `manuale-init` la si genera."
        )


_ACTIVE: Config | None = None


def active() -> Config:
    """La configurazione in uso, scoperta alla prima richiesta."""
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = Config.discover()
    return _ACTIVE


def use(config: Config) -> None:
    """Imposta la configurazione (test, o un chiamante che ne gestisce più d'una)."""
    global _ACTIVE
    _ACTIVE = config


@functools.lru_cache(maxsize=8)
def _path_re(extensions: tuple[str, ...]) -> re.Pattern[str]:
    """Riconosce un percorso citato. Le estensioni vengono dalla config: senza, un'ancora
    su un repo Go o PHP non verrebbe nemmeno vista."""
    alternatives = "|".join(re.escape(ext) for ext in extensions)
    return re.compile(rf"(?<![\w/.-])(?P<path>[\w./-]+\.(?:{alternatives}))(?![\w.])")


@dataclass(frozen=True)
class Anchor:
    """Una citazione `file · Lx–y` dentro un documento, con la sua posizione nel testo."""

    doc: Path
    file: Path
    start: int
    end: int
    dash: str
    span: tuple[int, int]  # posizione del token "Lx–y" nel testo del documento
    # In coda e con default: `Anchor` è frozen e viene costruita per nome nei test, quindi
    # un campo aggiunto altrove ne romperebbe una quarantina.
    root: Path | None = None

    @property
    def key(self) -> str:
        root = self.root or active().root
        rel_doc = self.doc.relative_to(root).as_posix()
        rel_file = self.file.relative_to(root).as_posix()
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


def resolve_file(name: str, cfg: Config | None = None) -> Path | None:
    for root in (cfg or active()).search_roots:
        candidate = root / name
        if candidate.is_file():
            return candidate.resolve()
    return None


def colliding_names(names: Iterable[str], cfg: Config | None = None) -> dict[str, list[Path]]:
    """Fra i nomi citati dal manuale, quelli che esistono in più di una `search_root`.

    Non è un errore: l'ordine di preferenza è deliberato. Ma su un repo dove quell'ordine
    non è stato curato a mano, una collisione silenziosa produce snippet sbagliati e
    credibili — il fallimento peggiore per un manuale che promette evidenza.

    Si guardano solo i nomi effettivamente usati come ancora: cercare le collisioni su
    tutto il repo significherebbe segnalare i `config.py` di `.venv`, che non interessano
    nessuno.
    """
    cfg = cfg or active()
    found: dict[str, list[Path]] = {}
    for name in sorted(set(names)):
        if "/" in name:  # percorso completo: non c'è ambiguità da risolvere
            continue
        candidates = []
        for root in cfg.search_roots:
            candidate = (root / name).resolve()
            if candidate.is_file() and candidate not in candidates:
                candidates.append(candidate)
        if len(candidates) > 1:
            found[name] = candidates
    return found


def parse_anchors(doc: Path, cfg: Config | None = None) -> list[Anchor]:
    """Estrae le ancore di un documento, riga per riga.

    Un'ancora non attraversa mai una riga di markdown, e sulla stessa riga un percorso può
    essere seguito da più range (le tabelle di riepilogo scrivono
    ``| `durable.py` | L42, L207–224 |``). Si associa quindi ogni range al percorso che lo
    precede sulla stessa riga, fermandosi al percorso successivo.
    """
    cfg = cfg or active()
    path_re = _path_re(cfg.extensions)
    anchors: list[Anchor] = []
    offset = 0
    for line in doc.read_text(encoding="utf-8").splitlines(keepends=True):
        paths = list(path_re.finditer(line))
        for index, match in enumerate(paths):
            resolved = resolve_file(match.group("path"), cfg)
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
                        root=cfg.root,
                    )
                )
        offset += len(line)
    return anchors


def all_anchors(cfg: Config | None = None) -> list[Anchor]:
    cfg = cfg or active()
    found: list[Anchor] = []
    for doc in sorted(cfg.handbook.rglob("*.md")):
        found.extend(parse_anchors(doc, cfg))
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


def load_lock(cfg: Config | None = None) -> dict[str, dict[str, Any]]:
    lockfile = (cfg or active()).lockfile
    if not lockfile.is_file():
        return {}
    data: dict[str, dict[str, Any]] = json.loads(lockfile.read_text(encoding="utf-8"))
    return data


def save_lock(entries: dict[str, dict[str, Any]], cfg: Config | None = None) -> None:
    lockfile = (cfg or active()).lockfile
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    ordered = {key: entries[key] for key in sorted(entries)}
    lockfile.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- esecuzione -----------------------------------------------------------------------


def run(mode: Literal["adopt", "check", "write"], cfg: Config | None = None) -> Report:
    cfg = cfg or active()
    lock = load_lock(cfg)
    report = Report()
    file_lines: dict[Path, list[str]] = {}
    fresh: dict[str, dict[str, Any]] = {}

    for anchor in all_anchors(cfg):
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
        save_lock(fresh, cfg)

    return report


def _entry(anchor: Anchor, print_: Fingerprint) -> dict[str, Any]:
    root = anchor.root or active().root
    return {
        "doc": anchor.doc.relative_to(root).as_posix(),
        "file": anchor.file.relative_to(root).as_posix(),
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


def summarize(report: Report, mode: str, cfg: Config | None = None) -> int:
    cfg = cfg or active()
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
            doc = result.anchor.doc.relative_to(cfg.handbook).as_posix()
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


VENDOR_HEADER = re.compile(r"^# vendored: (?P<plugin>\S+) (?P<version>\S+) · sha256:(?P<sha>\w+)")


def vendor_check(path: Path | None = None) -> int:
    """Verifica che la copia vendorizzata non sia stata modificata a mano.

    Rileva la deriva, non la impedisce: prima o poi qualcuno correggerà un bug qui invece
    che nel plugin, e da quel momento i due file divergono in silenzio. Il messaggio dice
    dove va portato il fix.
    """
    path = path or Path(__file__).resolve()
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    marked = [index for index, line in enumerate(lines) if VENDOR_HEADER.match(line)]
    if not marked:
        print("Copia non vendorizzata (nessun header di provenienza): niente da verificare.")
        return 0

    index = marked[0]
    match = VENDOR_HEADER.match(lines[index])
    assert match is not None
    body = "".join(lines[:index] + lines[index + 1 :])
    import hashlib

    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    if digest == match.group("sha"):
        return 0
    print(
        f"{path.name} diverge da {match.group('plugin')} {match.group('version')}.\n"
        "Se il cambiamento serve, portalo nel plugin e riallinea con "
        "`manuale-init --update`: una correzione che vive solo qui sparisce al prossimo "
        "aggiornamento."
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--adopt", action="store_true", help="registra le ancore nuove")
    group.add_argument("--check", action="store_true", help="verifica senza modificare (CI)")
    group.add_argument("--write", action="store_true", help="rilocalizza e riscrive i .md")
    group.add_argument(
        "--vendor-check", action="store_true", help="verifica la provenienza di questo script"
    )
    parser.add_argument("--config", type=Path, help="percorso della configurazione")
    parser.add_argument("--root", type=Path, help="radice del progetto (scavalca la config)")
    args = parser.parse_args(argv)

    if args.vendor_check:
        return vendor_check()

    if args.config is not None:
        use(Config.load(args.config.resolve()))
    elif args.root is not None:
        use(Config.discover(args.root.resolve()))

    cfg = active()
    cited = {anchor.file.name for anchor in all_anchors(cfg)}
    collisions = colliding_names(cited, cfg)
    if collisions:
        print(f"Attenzione: {len(collisions)} nomi citati risolvono in più search_roots.")
        for name, paths in list(collisions.items())[:5]:
            others = ", ".join(str(p.relative_to(cfg.root)) for p in paths[1:3])
            print(f"  {name} → {paths[0].relative_to(cfg.root)}  (anche: {others})")
        print("  Nelle tabelle di riepilogo usa i percorsi completi.\n")

    mode = "adopt" if args.adopt else "check" if args.check else "write"
    return summarize(run(mode, cfg), mode, cfg)


if __name__ == "__main__":
    sys.exit(main())
