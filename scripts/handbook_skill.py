"""Trasforma il manuale in una skill di navigazione per un agente.

Il manuale è scritto per essere consultato, ma un agente che apre il repo non sa che
esiste e non sa da dove entrare. Questo genera l'artefatto che glielo dice: un `SKILL.md`
con l'indice delle unità, cosa fa ciascuna, quali file tocca e dove sta la pagina
completa.

Il principio, che è quello del paper: **il manuale guida la ricerca, il repository resta
la fonte di verità**. La skill non contiene il codice e non lo riassume — contiene la
mappa che porta al punto giusto, e dice esplicitamente di verificare contro il codice
prima di concludere.

Il file generato è piccolo di proposito. Deve stare in contesto senza pesare: è un
instradamento, e il dettaglio si apre solo quando serve.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync = _load("handbook_sync")

_STAGE = re.compile(r"^## (?P<stage>.+?)\s*$", re.M)
_UNIT = re.compile(
    r"^### (?P<id>[\w.]+) · (?P<title>.+?)$"
    r".*?^> \*\*Responsabilità\.\*\* (?P<resp>.+?)(?=\n\n)"
    r".*?\[L3\]\((?P<link>L3/[\w-]+\.md)\)",
    re.M | re.S,
)


@dataclass
class Unit:
    id: str
    title: str
    stage: str
    responsibility: str
    page: str
    files: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    """Toglie i marcatori di citazione e normalizza gli spazi su una riga sola."""
    lines = [re.sub(r"^>\s?", "", line).strip() for line in text.splitlines()]
    return " ".join(" ".join(lines).split())


def collect_units(cfg: Any) -> list[Unit]:
    index = cfg.handbook / "L2_UNITA.md"
    text = index.read_text(encoding="utf-8")

    # A quale stadio appartiene un'unità: l'ultimo `## ...` che la precede.
    stages: list[tuple[int, str]] = [
        (m.start(), _clean(m.group("stage"))) for m in _STAGE.finditer(text)
    ]

    units: list[Unit] = []
    for match in _UNIT.finditer(text):
        stage = next(
            (name for pos, name in reversed(stages) if pos < match.start()),
            "",
        )
        page = cfg.handbook / match.group("link")
        # Ordinati per numero di ancore, non alfabeticamente: l'elenco viene troncato a
        # sei, e in ordine alfabetico i siti principali finiscono spesso nel taglio —
        # `App.tsx` prima di `runner.py` non aiuta nessuno.
        weight: dict[str, int] = {}
        if page.is_file():
            for anchor in sync.parse_anchors(page, cfg):
                key = anchor.file.relative_to(cfg.root).as_posix()
                weight[key] = weight.get(key, 0) + 1
        files = sorted(weight, key=lambda path: (-weight[path], path))
        units.append(
            Unit(
                id=match.group("id"),
                title=_clean(match.group("title")),
                stage=stage,
                responsibility=_clean(match.group("resp")),
                page=match.group("link"),
                files=files,
            )
        )
    return units


def render(cfg: Any, units: list[Unit], name: str) -> str:
    handbook = cfg.handbook.relative_to(cfg.root).as_posix()
    # Il nome configurato, non quello della cartella: in CI il checkout si chiama come il
    # repository, e un artefatto che cambia con il percorso non è verificabile.
    project = cfg.project or cfg.root.name

    by_stage: dict[str, list[Unit]] = {}
    for unit in units:
        by_stage.setdefault(unit.stage, []).append(unit)

    lines: list[str] = []
    lines.append("---")
    lines.append(f"name: {name}")
    lines.append("description: >-")
    lines.append(
        f"  Mappa dei comportamenti di `{project}`: dice quale unità governa un dato"
    )
    lines.append(
        "  comportamento, quali file tocca e dove leggerne il dettaglio con l'evidenza nel"
    )
    lines.append(
        "  codice. Usa questa skill PRIMA di cercare nel codice quando la domanda riguarda"
    )
    lines.append(
        "  cosa fa il sistema — «perché il comando è stato bloccato?», «dove si decide X?»,"
    )
    lines.append(
        "  «cosa devo toccare per cambiare Y?» — e prima di modificare un comportamento"
    )
    lines.append(
        "  esistente. Un comportamento vive sparso in più file: cercare per parole chiave"
    )
    lines.append("  trova i posti sbagliati o ne trova troppi.")
    lines.append("---")
    lines.append("")
    lines.append(f"# Comportamenti di {project}")
    lines.append("")
    lines.append(
        "Il manuale è organizzato per **comportamento**, non per modulo. Ogni affermazione"
    )
    lines.append(
        f"porta il punto esatto del codice che la rende vera. Le pagine stanno in `{handbook}/`."
    )
    lines.append("")
    lines.append("## Come usarla")
    lines.append("")
    lines.append("1. **Trova l'unità** nell'indice qui sotto: cerca il comportamento, non il file.")
    lines.append(
        "2. **Apri la sua pagina L3.** Le ultime due sezioni sono quelle che servono a"
    )
    lines.append(
        "   modificare: *Riepilogo evidenza* elenca i siti coinvolti, *Note per chi modifica*"
    )
    lines.append("   dice cosa toccare e quali invarianti non rompere.")
    lines.append(
        "3. **Segui le unità collegate.** Se due unità citano lo stesso file, un cambiamento"
    )
    lines.append("   in quel file le riguarda entrambe.")
    lines.append(
        "4. **Verifica contro il codice.** Il manuale guida la ricerca; la verità è il"
    )
    lines.append(
        "   repository. Apri i file citati e conferma prima di concludere: le righe possono"
    )
    lines.append("   essersi spostate, e una pagina può descrivere codice cambiato.")
    lines.append("")
    lines.append(
        f"Panoramica del flusso: `{handbook}/L1_SISTEMA.md`. Indice completo con ingressi,"
    )
    lines.append(f"uscite e stato di ogni unità: `{handbook}/L2_UNITA.md`.")
    lines.append("")
    lines.append("## Le unità")
    lines.append("")

    for stage, group in by_stage.items():
        lines.append(f"### {stage}")
        lines.append("")
        for unit in group:
            lines.append(f"**{unit.id} · {unit.title}** — {unit.responsibility}")
            if unit.files:
                shown = ", ".join(f"`{f}`" for f in unit.files[:6])
                extra = f" e altri {len(unit.files) - 6}" if len(unit.files) > 6 else ""
                lines.append(f"Tocca: {shown}{extra}.")
            lines.append(f"→ `{handbook}/{unit.page}`")
            lines.append("")

    lines.append("## File toccati da più unità")
    lines.append("")
    lines.append(
        "Sono i punti in cui comportamenti diversi si incontrano: modificarli ne riguarda"
    )
    lines.append("più di uno.")
    lines.append("")
    shared: dict[str, list[str]] = {}
    for unit in units:
        for path in unit.files:
            shared.setdefault(path, []).append(unit.id)
    for path, ids in sorted(shared.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(ids) > 1:
            lines.append(f"- `{path}` → unità {', '.join(ids)}")
    lines.append("")
    lines.append("## Se il manuale e il codice non concordano")
    lines.append("")
    lines.append(
        "Dillo invece di adattarti: significa che il codice è cambiato e la pagina è"
    )
    lines.append(
        "rimasta indietro. `make handbook-check` verifica che ogni riferimento sia dove il"
    )
    lines.append("manuale dice.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, help="percorso della configurazione")
    parser.add_argument("--out", type=Path, help="file SKILL.md da scrivere")
    parser.add_argument("--name", default="manuale", help="nome della skill")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verifica che il file su disco sia aggiornato, senza riscriverlo (CI)",
    )
    args = parser.parse_args(argv)

    if args.config is not None:
        sync.use(sync.Config.load(args.config.resolve()))
    cfg = sync.active()

    out = (args.out or cfg.root / ".claude" / "skills" / args.name / "SKILL.md").resolve()
    units = collect_units(cfg)

    if not units:
        # Manuale vuoto: è lo stato di un repo appena inizializzato, non un errore.
        # Se ci fosse una skill vecchia di quando le unità c'erano, va rimossa — altrimenti
        # instraderebbe verso pagine inesistenti; ma con il manuale svuotato di proposito
        # non c'è niente da generare, e il gate deve restare verde.
        stale = out.is_file() and out.read_text(encoding="utf-8").strip()
        if args.check and stale:
            print(f"{out.relative_to(cfg.root)} esiste ma il manuale non ha unità: rimuovila.")
            return 1
        print("Manuale senza unità: niente skill da generare (repo appena inizializzato?).")
        return 0

    body = render(cfg, units, args.name)
    files = {path for unit in units for path in unit.files}
    summary = (
        f"{out.relative_to(cfg.root)} · {len(units)} unità · {len(files)} file citati "
        f"· {len(body) // 1024} KB"
    )

    if args.check:
        # La skill è versionata — deve esserlo, o un clone fresco non la troverebbe — e
        # quindi può invecchiare rispetto al manuale. Qui la si tratta come un lockfile:
        # non si rigenera, si verifica.
        current = out.read_text(encoding="utf-8") if out.is_file() else ""
        if current == body:
            print(f"{summary} · aggiornata")
            return 0
        print(
            f"{out.relative_to(cfg.root)} non riflette il manuale.\n"
            "Un agente la leggerebbe e verrebbe instradato su un indice vecchio: "
            "`make handbook-skill` per rigenerarla."
        )
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
