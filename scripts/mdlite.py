"""Markdown → HTML, limitato ai costrutti che il manuale usa davvero.

Non è un renderer generico e non prova a esserlo: importare una libreria per rendere
quindici file dallo schema noto significherebbe aggiungere una dipendenza a un progetto
che oggi non ne ha nessuna per il rendering. Qui si coprono heading, paragrafi, enfasi,
codice inline, link, blocchi recintati, tabelle GFM, citazioni, liste e righe orizzontali —
l'inventario completo dello schema, verificato sui file reali.

Due scelte che vale la pena conoscere prima di modificarlo:

**Nessun HTML inline.** Non compare in nessuna pagina, e accettarlo significherebbe dover
distinguere il markup voluto da quello ostile. Un `<` nel sorgente diventa `&lt;` e basta.

**Prima si escapa, poi si formatta.** L'ordine opposto — formattare e poi escapare — è il
modo classico di trasformare un renderer in una falla: il markup appena generato verrebbe
escapato insieme al contenuto. I frammenti di codice inline vengono messi da parte con un
sentinella prima di applicare enfasi e link, così un asterisco dentro `` `a*b` `` resta un
asterisco.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

_FENCE = re.compile(r"^```(?P<lang>[\w+-]*)\s*$")
_HEADING = re.compile(r"^(?P<level>#{1,4})\s+(?P<text>.+?)\s*$")
_HR = re.compile(r"^-{3,}\s*$")
_QUOTE = re.compile(r"^>\s?(?P<text>.*)$")
_BULLET = re.compile(r"^(?P<indent>\s*)[-*]\s+(?P<text>.+)$")
_NUMBER = re.compile(r"^(?P<indent>\s*)\d+\.\s+(?P<text>.+)$")
_TABLE_SEP = re.compile(r"^\s*\|(?:\s*:?-{2,}:?\s*\|)+\s*$")

_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_ITALIC = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", re.S)

# Sentinella fuori dall'alfabeto del markdown: nessun documento può contenerlo.
_MARK = "\x00"
_SLOT = re.compile(rf"{_MARK}(\d+){_MARK}")


def slug(text: str) -> str:
    """Ancora di sezione nello stile di GitHub, per far funzionare i link `#...`.

    `### 3.1 · Igiene dei blocchi-file` → `31--igiene-dei-blocchi-file`: i caratteri non
    alfanumerici spariscono e ogni spazio residuo diventa un trattino, quindi `·` fra due
    spazi ne produce due.
    """
    plain = _CODE.sub(r"\1", text)
    plain = _LINK.sub(r"\1", plain)
    plain = plain.replace("**", "").replace("*", "")
    kept = "".join(ch if (ch.isalnum() or ch in " -_") else "" for ch in plain.lower())
    return kept.strip().replace(" ", "-")


@dataclass
class _Inline:
    """Raccoglie i frammenti da non toccare (codice) durante la formattazione."""

    slots: list[str] = field(default_factory=list)

    def park(self, markup: str) -> str:
        self.slots.append(markup)
        return f"{_MARK}{len(self.slots) - 1}{_MARK}"

    def restore(self, text: str) -> str:
        return _SLOT.sub(lambda m: self.slots[int(m.group(1))], text)


def inline(text: str) -> str:
    """Formatta una porzione di testo: codice, link, grassetto, corsivo."""
    parked = _Inline()
    escaped = html.escape(text, quote=False)

    def code(match: re.Match[str]) -> str:
        return parked.park(f"<code>{match.group(1)}</code>")

    escaped = _CODE.sub(code, escaped)

    def link(match: re.Match[str]) -> str:
        label, href = match.group(1), match.group(2)
        return parked.park(f'<a href="{html.escape(href, quote=True)}">{label}</a>')

    escaped = _LINK.sub(link, escaped)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC.sub(r"<em>\1</em>", escaped)
    return parked.restore(escaped)


def _split_row(line: str) -> list[str]:
    """Divide una riga di tabella sui `|`, ignorando quelli dentro il codice inline.

    Serve davvero: le tabelle del manuale contengono celle come
    `` `f"{doc}|{file}|{start}-{end}"` ``, e una divisione ingenua le spezzerebbe in tre.
    """
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    for char in line.strip().strip("|"):
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
    cells.append("".join(current))
    return [cell.strip() for cell in cells]


def render(markdown: str) -> str:
    """Rende un documento intero. Ritorna un frammento, non una pagina."""
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]

        if not line.strip():
            index += 1
            continue

        fence = _FENCE.match(line)
        if fence:
            index += 1
            body: list[str] = []
            while index < len(lines) and not _FENCE.match(lines[index]):
                body.append(lines[index])
                index += 1
            index += 1  # la riga di chiusura
            lang = fence.group("lang")
            attr = f' class="language-{lang}"' if lang else ""
            out.append(
                f"<pre><code{attr}>{html.escape(chr(10).join(body), quote=False)}</code></pre>"
            )
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group("level"))
            text = heading.group("text")
            out.append(f'<h{level} id="{slug(text)}">{inline(text)}</h{level}>')
            index += 1
            continue

        if _HR.match(line):
            out.append("<hr>")
            index += 1
            continue

        if _QUOTE.match(line):
            block: list[str] = []
            while index < len(lines) and _QUOTE.match(lines[index]):
                match = _QUOTE.match(lines[index])
                assert match is not None
                block.append(match.group("text"))
                index += 1
            out.append(f"<blockquote>{render(chr(10).join(block))}</blockquote>")
            continue

        starts_table = (
            line.lstrip().startswith("|")
            and index + 1 < len(lines)
            and _TABLE_SEP.match(lines[index + 1]) is not None
        )
        if starts_table:
            header = _split_row(line)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                rows.append(_split_row(lines[index]))
                index += 1
            head = "".join(f"<th>{inline(cell)}</th>" for cell in header)
            body_rows = "".join(
                "<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            out.append(
                f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
                f"<tbody>{body_rows}</tbody></table></div>"
            )
            continue

        bullet, number = _BULLET.match(line), _NUMBER.match(line)
        if bullet or number:
            tag = "ul" if bullet else "ol"
            pattern = _BULLET if bullet else _NUMBER
            items: list[str] = []
            while index < len(lines):
                match = pattern.match(lines[index])
                if not match:
                    # Riga di continuazione: rientrata e non vuota. Le voci del manuale
                    # vanno spesso a capo, e senza questo la seconda riga diventerebbe un
                    # paragrafo staccato dalla lista.
                    if items and lines[index].startswith((" ", "\t")) and lines[index].strip():
                        items[-1] += " " + lines[index].strip()
                        index += 1
                        continue
                    break
                items.append(match.group("text"))
                index += 1
            body_items = "".join(f"<li>{inline(item)}</li>" for item in items)
            out.append(f"<{tag}>{body_items}</{tag}>")
            continue

        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip():
            candidate = lines[index]
            if (
                _HEADING.match(candidate)
                or _FENCE.match(candidate)
                or _HR.match(candidate)
                or _QUOTE.match(candidate)
                or _BULLET.match(candidate)
                or _NUMBER.match(candidate)
                or candidate.lstrip().startswith("|")
            ):
                break
            paragraph.append(candidate.strip())
            index += 1
        if paragraph:
            out.append(f"<p>{inline(' '.join(paragraph))}</p>")

    return "".join(out)
