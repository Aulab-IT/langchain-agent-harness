#!/usr/bin/env python3
"""Validate a Keynote outline JSON against the Aulab deck rules."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_YELLOW = "#ffed3a"
REQUIRED_WHITE = "#ffffff"
REQUIRED_BLACK = "#000000"
REQUIRED_LOGO_ASSET = "assets/aulab_logo_watermark_48.png.b64"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: validate_outline.py outline.json", file=sys.stderr)
        return 2

    path = Path(argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    metadata = data.get("metadata", {})
    palette = metadata.get("palette", {})
    slides = data.get("slides", [])

    errors: list[str] = []
    if palette.get("yellow") != REQUIRED_YELLOW:
        errors.append("palette.yellow must be #ffed3a")
    if palette.get("white") != REQUIRED_WHITE:
        errors.append("palette.white must be #ffffff")
    if palette.get("black") != REQUIRED_BLACK:
        errors.append("palette.black must be #000000")
    if not metadata.get("logo_path"):
        errors.append("metadata.logo_path is required")
    else:
        logo_path = Path(metadata["logo_path"])
        if not logo_path.exists():
            errors.append(f"metadata.logo_path does not exist: {logo_path}")
        elif logo_path.read_bytes()[:8].hex() != "89504e470d0a1a0a":
            errors.append(f"metadata.logo_path is not a PNG: {logo_path}")
    if metadata.get("logo_asset") != REQUIRED_LOGO_ASSET:
        errors.append(f"metadata.logo_asset must be {REQUIRED_LOGO_ASSET}")

    for idx, slide in enumerate(slides, start=1):
        title = slide.get("title")
        slide_type = slide.get("type", "content")
        notes = slide.get("notes", [])
        if not title:
            errors.append(f"slide {idx}: title is required")
        if not notes:
            errors.append(f"slide {idx}: notes are required")
        if slide_type == "chapter":
            if slide.get("background") != REQUIRED_YELLOW:
                errors.append(f"slide {idx}: chapter background must be #ffed3a")
            if slide.get("text_color") != REQUIRED_BLACK:
                errors.append(f"slide {idx}: chapter text_color must be #000000")
            if slide.get("watermark") is not False:
                errors.append(f"slide {idx}: chapter slides must not have watermark")
        else:
            if slide.get("watermark") is not True:
                errors.append(f"slide {idx}: content slides must have watermark")
            if slide.get("text_color") != REQUIRED_BLACK:
                errors.append(f"slide {idx}: content text_color must be #000000")

    if errors:
        print("outline_valid= no")
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    chapter_count = sum(1 for s in slides if s.get("type") == "chapter")
    watermarked = sum(1 for s in slides if s.get("watermark") is True)
    print("outline_valid= yes")
    print(f"slides= {len(slides)}")
    print(f"chapters= {chapter_count}")
    print(f"watermarked_content_slides= {watermarked}")
    print(f"logo_asset= {metadata.get('logo_asset')}")
    print(f"logo_path= {metadata.get('logo_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
