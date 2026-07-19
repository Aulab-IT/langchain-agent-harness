"""Genera l'artefatto navigabile del manuale: una pagina sola, senza dipendenze.

Il manuale è quindici file markdown pieni di riferimenti `file · L120–140`. Leggerlo
significa saltare avanti e indietro fra l'editor e la prosa. Qui ogni ancora diventa un
bottone che apre il codice citato sotto la frase che lo descrive.

**Le righe sono quelle vere, non quelle scritte nel markdown.** Gli snippet si risolvono
con `relocate` dello script di sync, che ritrova l'impronta registrata nel lockfile: se il
codice si è spostato e il `.md` non è ancora stato riscritto, l'artefatto mostra comunque
il blocco giusto. E se l'impronta non si ritrova — esiti `ambiguous` o `lost` — lo snippet
non viene mostrato affatto: si vede un badge «evidenza non risolta». Mostrare righe
plausibili e false è esattamente il fallimento che il lockfile esiste per prevenire.

La pagina è autonoma: niente CDN, niente font remoti, niente fetch. È il vincolo di una
CSP severa, ma è anche ciò che la rende apribile da `file://` e archiviabile.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass, field
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
mdlite = _load("mdlite")

# Oltre questa soglia lo snippet si elide al centro: un'ancora enorme renderebbe la pagina
# illeggibile prima ancora che pesante.
MAX_SNIPPET_LINES = 400


@dataclass
class Snippet:
    file: str
    start: int
    end: int
    lines: list[str]
    first: int  # numero della prima riga mostrata, contesto compreso
    elided: int = 0


@dataclass
class AnchorView:
    id: str
    file: str
    label: str
    outcome: str
    start: int
    end: int
    snippet: int | None = None
    detail: str = ""


@dataclass
class Page:
    slug: str
    kind: str  # "index" | "unit"
    title: str
    unit: str = ""
    stage: str = ""
    html: str = ""
    headings: list[dict[str, str]] = field(default_factory=list)
    anchors: list[AnchorView] = field(default_factory=list)
    text: str = ""


_UNIT_LINE = re.compile(r"^\*\*Unità:\*\*\s*(?P<stage>.+?)\s*→\s*\[(?P<id>[^\]]+)\]", re.M)
_TITLE = re.compile(r"^#\s+(?P<title>.+?)\s*$", re.M)


def _read_lines(path: Path, cache: dict[Path, list[str]]) -> list[str]:
    if path not in cache:
        cache[path] = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return cache[path]


def build_snippet(lines: list[str], start: int, end: int, context: int) -> Snippet:
    """Estrae il blocco citato più un po' di contesto, elidendo il centro se è enorme."""
    first = max(1, start - context)
    last = min(len(lines), end + context)
    body = lines[first - 1 : last]
    elided = 0
    if len(body) > MAX_SNIPPET_LINES:
        keep = MAX_SNIPPET_LINES // 2
        elided = len(body) - 2 * keep
        body = [*body[:keep], f"… {elided} righe omesse …", *body[-keep:]]
    return Snippet(file="", start=start, end=end, lines=body, first=first, elided=elided)


def collect(cfg: Any) -> tuple[list[Page], list[Snippet], dict[str, int]]:
    """Costruisce il modello: pagine rese, snippet deduplicati, conteggi."""
    lock = sync.load_lock(cfg)
    file_cache: dict[Path, list[str]] = {}
    snippets: list[Snippet] = []
    by_range: dict[tuple[str, int, int], int] = {}
    counts = {"ok": 0, "relocated": 0, "ambiguous": 0, "lost": 0, "new": 0}
    pages: list[Page] = []

    for doc in sorted(cfg.handbook.rglob("*.md")):
        source = doc.read_text(encoding="utf-8")
        anchors = sync.parse_anchors(doc, cfg)

        views: list[AnchorView] = []
        # Le sostituzioni partono dal fondo: così gli offset delle ancore precedenti
        # restano validi mentre il testo cambia lunghezza.
        marked = source
        for position, anchor in enumerate(sorted(anchors, key=lambda a: a.span[0], reverse=True)):
            index = len(anchors) - 1 - position
            lines = _read_lines(anchor.file, file_cache)
            entry = lock.get(anchor.key)

            if entry is None:
                result = sync.Result(anchor, "new", anchor.start, anchor.end, "non nel lockfile")
            else:
                result = sync.relocate(
                    lines,
                    anchor,
                    sync.Fingerprint(
                        head=entry["head"],
                        head_offset=int(entry["head_offset"]),
                        tail=entry["tail"],
                        tail_offset=int(entry["tail_offset"]),
                    ),
                )
            counts[result.outcome] = counts.get(result.outcome, 0) + 1

            rel = anchor.file.relative_to(cfg.root).as_posix()
            view = AnchorView(
                id=f"a{index}",
                file=rel,
                label=f"{anchor.file.name} · {anchor.render(anchor.start, anchor.end)}",
                outcome=result.outcome,
                start=result.start,
                end=result.end,
                detail=result.detail,
            )
            # Lo snippet si mostra solo quando l'evidenza è stata ritrovata davvero.
            if result.outcome in ("ok", "relocated"):
                key = (rel, result.start, result.end)
                if key not in by_range:
                    snippet = build_snippet(
                        lines, result.start, result.end, cfg.html_context_lines
                    )
                    snippet.file = rel
                    snippets.append(snippet)
                    by_range[key] = len(snippets) - 1
                view.snippet = by_range[key]

            begin, finish = anchor.span
            marked = marked[:begin] + f"\x00A{index}\x00" + marked[finish:]
            views.append(view)

        views.reverse()
        rendered = mdlite.render(marked)
        # `views` legata per valore: la sostituzione avviene subito, ma un riferimento
        # libero alla variabile di ciclo è il modo classico di prendersi un bug quando
        # qualcuno rende la chiamata pigra.
        rendered = re.sub(
            r"\x00A(\d+)\x00",
            lambda m, v=views: _anchor_button(v[int(m.group(1))]),
            rendered,
        )

        title_match = _TITLE.search(source)
        unit_match = _UNIT_LINE.search(source)
        pages.append(
            Page(
                slug=doc.relative_to(cfg.handbook).with_suffix("").as_posix(),
                kind="unit" if doc.parent.name == "L3" else "index",
                title=title_match.group("title").strip() if title_match else doc.stem,
                unit=unit_match.group("id") if unit_match else "",
                stage=unit_match.group("stage").strip() if unit_match else "",
                html=rendered,
                headings=[
                    {"level": line.split(" ")[0].count("#"), "text": line.lstrip("# ").strip(),
                     "id": mdlite.slug(line.lstrip("# ").strip())}
                    for line in _outside_fences(source)
                    if re.match(r"^#{2,3}\s", line)
                ],
                anchors=views,
                text=" ".join(_outside_fences(source)),
            )
        )

    return pages, snippets, counts


def _outside_fences(source: str) -> list[str]:
    lines: list[str] = []
    inside = False
    for line in source.splitlines():
        if line.startswith("```"):
            inside = not inside
            continue
        if not inside:
            lines.append(line)
    return lines


def _anchor_button(view: AnchorView) -> str:
    label = html.escape(view.label, quote=False)
    if view.snippet is None:
        title = html.escape(view.detail or "evidenza non risolta", quote=True)
        return (
            f'<span class="anchor unresolved" title="{title}">{label}'
            f'<span class="badge">non risolta</span></span>'
        )
    moved = ' data-moved="1"' if view.outcome == "relocated" else ""
    return (
        f'<button class="anchor" type="button" aria-expanded="false" '
        f'data-snippet="{view.snippet}"{moved}>{label}</button>'
    )


def build_page(
    cfg: Any, pages: list[Page], snippets: list[Snippet], counts: dict[str, int]
) -> str:
    model = {
        "root": str(cfg.root),
        "editor": cfg.html_editor,
        "counts": counts,
        "pages": [asdict(page) for page in pages],
        "snippets": [asdict(snippet) for snippet in snippets],
    }
    payload = json.dumps(model, ensure_ascii=False).replace("</", "<\\/")
    css = (HERE / "assets" / "handbook.css").read_text(encoding="utf-8")
    js = (HERE / "assets" / "handbook.js").read_text(encoding="utf-8")
    unresolved = counts.get("ambiguous", 0) + counts.get("lost", 0) + counts.get("new", 0)
    total = sum(counts.values())
    warn = " warn" if unresolved else ""
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harness Handbook</title>
<style>{css}</style>
</head>
<body>
<header class="top">
  <div class="brand">Harness Handbook</div>
  <input id="q" type="search" placeholder="Cerca unità, sezione o file…  /" autocomplete="off">
  <div class="meta">
    <span class="pill{warn}">{total} ancore · {unresolved} non risolte</span>
    <button id="theme" type="button" title="Tema chiaro/scuro">◐</button>
  </div>
</header>
<div class="layout">
  <nav id="rail"></nav>
  <main id="main"></main>
</div>
<script type="application/json" id="model">{payload}</script>
<script>{js}</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, help="percorso della configurazione")
    parser.add_argument("--out", type=Path, help="file di destinazione")
    args = parser.parse_args(argv)

    if args.config is not None:
        sync.use(sync.Config.load(args.config.resolve()))
    cfg = sync.active()

    pages, snippets, counts = collect(cfg)
    out = (args.out or cfg.html_out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page(cfg, pages, snippets, counts), encoding="utf-8")

    unresolved = counts.get("ambiguous", 0) + counts.get("lost", 0) + counts.get("new", 0)
    size = out.stat().st_size / 1024
    print(
        f"{out.relative_to(cfg.root)} · {len(pages)} pagine · {sum(counts.values())} ancore "
        f"· {len(snippets)} snippet · {size:.0f} KB"
    )
    if unresolved:
        print(f"  {unresolved} ancore senza evidenza risolta: `handbook_sync --check` dice quali.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
