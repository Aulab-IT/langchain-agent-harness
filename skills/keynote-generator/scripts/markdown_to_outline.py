#!/usr/bin/env python3
"""Convert a simple Markdown deck into a branded Keynote slide outline JSON.

Supported input:
- optional YAML-like front matter delimited by ---
- `# Capitolo: Title` or `# Chapter: Title` starts a chapter divider slide
- each other H1 (`# Title`) starts a content slide
- bullet lines (`- item`, `* item`) become slide bullets
- blockquote lines (`> note`) become speaker notes
- content slides without explicit notes receive generated speaker notes

Usage:
  python scripts/markdown_to_outline.py input.md output.json
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path
from typing import Any

YELLOW = "#ffed3a"
WHITE = "#ffffff"
BLACK = "#000000"
SKILL_ROOT = Path(__file__).resolve().parents[1]
LOGO_B64 = SKILL_ROOT / "assets" / "aulab_logo_watermark_48.png.b64"
DEFAULT_LOGO_PATH = "/workspace/work/keynote-generator-assets/aulab_logo_watermark_48.png"


def materialize_logo_asset() -> str:
    output = Path(DEFAULT_LOGO_PATH)
    if output.exists() and output.read_bytes()[:8].hex() == "89504e470d0a1a0a":
        return str(output)
    if not LOGO_B64.exists():
        raise FileNotFoundError(f"Missing skill logo asset: {LOGO_B64}")
    raw = base64.b64decode("".join(LOGO_B64.read_text(encoding="ascii").split()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    if output.read_bytes()[:8].hex() != "89504e470d0a1a0a":
        raise ValueError(f"Materialized logo is not a valid PNG: {output}")
    return str(output)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end].strip()
    body = text[end + len("\n---") :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body


def clean_inline_markdown(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
    return value.strip()


def is_chapter_title(title: str) -> bool:
    normalized = title.strip().lower()
    return normalized.startswith(("capitolo:", "chapter:", "capitolo ", "chapter "))


def normalize_chapter_title(title: str) -> str:
    cleaned = re.sub(r"^(capitolo|chapter)\s*:?\s*", "", title.strip(), flags=re.I)
    return cleaned or title.strip()


def make_slide(title: str, slide_type: str = "content") -> dict[str, Any]:
    if slide_type == "chapter":
        return {
            "type": "chapter",
            "title": normalize_chapter_title(title),
            "bullets": [],
            "notes": [],
            "background": YELLOW,
            "text_color": BLACK,
            "watermark": False,
        }
    return {
        "type": "content",
        "title": title,
        "bullets": [],
        "notes": [],
        "background": WHITE,
        "text_color": BLACK,
        "watermark": True,
    }


def ensure_notes(slide: dict[str, Any]) -> None:
    if slide.get("type") == "content" and not slide.get("notes"):
        bullets = slide.get("bullets") or []
        if bullets:
            slide["notes"] = [
                "Presentare la slide evidenziando: " + "; ".join(str(b) for b in bullets[:4]) + "."
            ]
        else:
            slide["notes"] = [f"Presentare il messaggio principale della slide: {slide.get('title', 'Untitled')}."]
    elif slide.get("type") == "chapter" and not slide.get("notes"):
        slide["notes"] = [f"Introdurre il capitolo: {slide.get('title', 'Untitled')}."]


def parse_markdown(text: str) -> dict[str, Any]:
    meta, body = parse_front_matter(text)
    slides: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    logo_path = materialize_logo_asset()

    def ensure_current() -> dict[str, Any]:
        nonlocal current
        if current is None:
            current = make_slide(meta.get("title", "Untitled"), "content")
            slides.append(current)
        return current

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            title = clean_inline_markdown(stripped[2:])
            slide_type = "chapter" if is_chapter_title(title) else "content"
            current = make_slide(title, slide_type)
            slides.append(current)
        elif stripped.startswith(("- ", "* ")):
            ensure_current()["bullets"].append(clean_inline_markdown(stripped[2:]))
        elif stripped.startswith(">"):
            ensure_current()["notes"].append(clean_inline_markdown(stripped.lstrip("> ")))
        elif stripped.startswith("## "):
            ensure_current()["bullets"].append(clean_inline_markdown(stripped[3:]))
        else:
            ensure_current()["notes"].append(clean_inline_markdown(stripped))

    if not slides:
        slides.append(make_slide(meta.get("title", "Untitled"), "content"))

    for slide in slides:
        ensure_notes(slide)

    return {
        "metadata": {
            "title": meta.get("title") or slides[0]["title"],
            "subtitle": meta.get("subtitle", ""),
            "author": meta.get("author", ""),
            "source": meta.get("source", "markdown"),
            "logo_path": meta.get("logo_path", logo_path),
            "logo_asset": "assets/aulab_logo_watermark_48.png.b64",
            "palette": {
                "yellow": meta.get("yellow", YELLOW),
                "white": meta.get("white", WHITE),
                "black": meta.get("black", BLACK),
            },
            "watermark": {
                "enabled": True,
                "position": "top-right",
                "size": "small",
                "default_logo_path": logo_path,
                "skip_on_slide_types": ["chapter"],
            },
        },
        "slides": slides,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: markdown_to_outline.py input.md output.json", file=sys.stderr)
        return 2
    input_path = Path(argv[1])
    output_path = Path(argv[2])
    text = input_path.read_text(encoding="utf-8")
    outline = parse_markdown(text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(outline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    chapter_count = sum(1 for s in outline["slides"] if s.get("type") == "chapter")
    print(f"Wrote {len(outline['slides'])} slides ({chapter_count} chapters) to {output_path}")
    print(f"logo_path= {outline['metadata']['logo_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
