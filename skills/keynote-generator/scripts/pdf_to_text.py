#!/usr/bin/env python3
"""Extract text from a PDF into a UTF-8 text file.

Requires one of these optional Python packages:
- pypdf
- PyPDF2

Install example in a workspace-local environment:
  python -m pip install --target /workspace/.pylib pypdf
  PYTHONPATH=/workspace/.pylib python scripts/pdf_to_text.py input.pdf work/input.txt

Usage:
  python scripts/pdf_to_text.py input.pdf output.txt
"""
from __future__ import annotations

import sys
from pathlib import Path


def load_reader():
    try:
        from pypdf import PdfReader  # type: ignore
        return PdfReader
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
            return PdfReader
        except Exception as exc:
            raise SystemExit(
                "Missing PDF reader dependency. Install pypdf locally, for example:\n"
                "  python -m pip install --target /workspace/.pylib pypdf\n"
                "Then run with:\n"
                "  PYTHONPATH=/workspace/.pylib python scripts/pdf_to_text.py input.pdf output.txt"
            ) from exc


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: pdf_to_text.py input.pdf output.txt", file=sys.stderr)
        return 2

    input_path = Path(argv[1])
    output_path = Path(argv[2])
    PdfReader = load_reader()
    reader = PdfReader(str(input_path))

    chunks: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        chunks.append(f"\n\n--- Page {idx} ---\n{text.strip()}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(chunks).strip() + "\n", encoding="utf-8")
    print(f"Extracted {len(reader.pages)} pages to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
