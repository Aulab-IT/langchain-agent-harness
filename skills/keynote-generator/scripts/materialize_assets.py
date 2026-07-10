#!/usr/bin/env python3
"""Materialize persistent skill assets into the workspace.

The skill stores the Aulab watermark logo as a base64 resource under
`assets/aulab_logo_watermark_48.png.b64`. This script decodes it into a regular
PNG file usable by PPTX generation and by AppleScript/Keynote.

Usage:
  python /skills/keynote-generator/scripts/materialize_assets.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
LOGO_B64 = SKILL_ROOT / "assets" / "aulab_logo_watermark_48.png.b64"
OUTPUT_DIR = Path("/workspace/work/keynote-generator-assets")
OUTPUT_LOGO = OUTPUT_DIR / "aulab_logo_watermark_48.png"


def materialize_logo() -> Path:
    if not LOGO_B64.exists():
        raise FileNotFoundError(f"Missing skill asset: {LOGO_B64}")
    raw = base64.b64decode("".join(LOGO_B64.read_text(encoding="ascii").split()))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_LOGO.write_bytes(raw)
    if OUTPUT_LOGO.read_bytes()[:8].hex() != "89504e470d0a1a0a":
        raise ValueError(f"Materialized logo is not a valid PNG: {OUTPUT_LOGO}")
    return OUTPUT_LOGO


def main() -> int:
    path = materialize_logo()
    print(f"logo_asset_materialized= {path}")
    print(f"logo_asset_size= {path.stat().st_size}")
    print("logo_asset_png= True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
