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
        help="Esegue tutti i notebook; 01-06 usano OPENAI_API_KEY da .env.",
    )
    parser.add_argument(
        "--execute-offline",
        action="store_true",
        help="Esegue i notebook 07-12, che usano solo la standard library.",
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
    live_langchain = path.name[:2].isdigit() and int(path.name[:2]) <= 6
    if live_langchain and ("ChatOpenAI" not in source or "create_agent" not in source):
        raise AssertionError(f"{path.name}: manca un micro-esempio LangChain reale.")
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            compile(str(cell.source), f"{path.name}:cell-{index}", "exec")
            if index == 0 or notebook.cells[index - 1].cell_type != "markdown":
                raise AssertionError(f"{path.name}: cella {index} senza spiegazione precedente.")
            if not str(notebook.cells[index - 1].source).startswith(
                "### Spiegazione del blocco"
            ):
                raise AssertionError(
                    f"{path.name}: cella {index} senza spiegazione didattica dedicata."
                )
            if (
                index + 1 >= len(notebook.cells)
                or notebook.cells[index + 1].cell_type != "markdown"
            ):
                raise AssertionError(f"{path.name}: cella {index} senza output atteso successivo.")
            if not str(notebook.cells[index + 1].source).startswith("### Output atteso"):
                raise AssertionError(
                    f"{path.name}: cella {index} senza commento sull'output atteso."
                )
    contract = notebook.metadata.get("didactic_contract", {})
    if contract.get("version") != 1 or contract.get("extra_examples", 0) < 2:
        raise AssertionError(f"{path.name}: contratto didattico assente o incompleto.")
    if sum(cell.cell_type == "code" for cell in notebook.cells) < 5:
        raise AssertionError(f"{path.name}: esempi codice insufficienti.")
    return notebook


def main() -> None:
    args = parse_args()
    notebooks = sorted((ROOT / "notebooks").glob("*.ipynb"))
    if len(notebooks) != 12:
        raise RuntimeError(f"Attesi 12 notebook, trovati {len(notebooks)}.")

    loaded = [(path, validate_notebook(path)) for path in notebooks]
    for path, _ in loaded:
        print(f"VALID {path.relative_to(ROOT)}")

    if not args.execute and not args.execute_offline:
        print(
            "Validazione strutturale completata. Usa --execute-offline per 07-12 "
            "o --execute per tutti."
        )
        return

    if args.execute:
        load_dotenv(ROOT / ".env", override=False)
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit(
                "OPENAI_API_KEY non configurata in .env: esecuzione live impossibile."
            )

    with tempfile.TemporaryDirectory() as temporary:
        for path, notebook in loaded:
            if args.execute_offline and int(path.name[:2]) <= 6:
                continue
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
