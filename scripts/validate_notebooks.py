from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import nbformat
from dotenv import load_dotenv
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
PROHIBITED_REFERENCES = (
    "from agent_harness",
    "import agent_harness",
    "from steps",
    "import steps",
    "sys.path",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Valida i notebook didattici.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Esegue tutte le celle usando OPENAI_API_KEY da .env.",
    )
    return parser.parse_args()


def validate_notebook(path: Path) -> nbformat.NotebookNode:
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    source = "\n".join(
        str(cell.source) for cell in notebook.cells if cell.cell_type == "code"
    )
    for reference in PROHIBITED_REFERENCES:
        if reference in source:
            raise AssertionError(f"{path.name}: riferimento esterno vietato: {reference}")
    if "ChatOpenAI" not in source or "create_agent" not in source:
        raise AssertionError(f"{path.name}: manca un micro-esempio LangChain reale.")
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            compile(str(cell.source), f"{path.name}:cell-{index}", "exec")
    return notebook


def main() -> None:
    args = parse_args()
    notebooks = sorted((ROOT / "notebooks").glob("*.ipynb"))
    if len(notebooks) != 5:
        raise RuntimeError(f"Attesi 5 notebook, trovati {len(notebooks)}.")

    loaded = [(path, validate_notebook(path)) for path in notebooks]
    for path, _ in loaded:
        print(f"VALID {path.relative_to(ROOT)}")

    if not args.execute:
        print("Validazione strutturale completata. Usa --execute per le chiamate live.")
        return

    load_dotenv(ROOT / ".env", override=False)
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY non configurata in .env: esecuzione live impossibile.")

    with tempfile.TemporaryDirectory() as temporary:
        for path, notebook in loaded:
            NotebookClient(
                notebook,
                timeout=300,
                kernel_name="python3",
                resources={"metadata": {"path": str(ROOT)}},
            ).execute(cwd=str(ROOT))
            target = Path(temporary) / path.name
            nbformat.write(notebook, target)
            print(f"EXECUTED {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
