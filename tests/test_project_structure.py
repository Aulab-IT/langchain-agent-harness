from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parents[1]


def test_every_increment_has_code_and_guide() -> None:
    steps = sorted(
        path
        for path in (ROOT / "steps").iterdir()
        if path.is_dir() and path.name[:2].isdigit()
    )
    assert [path.name[:2] for path in steps] == [f"{index:02d}" for index in range(20)]
    for step in steps:
        assert (step / "app.py").is_file(), step
        guide = step / "GUIDA.md"
        changelog = step / "CHANGELOG.md"
        assert guide.is_file(), step
        assert changelog.is_file(), step
        assert len(guide.read_text(encoding="utf-8").split()) >= 100, step
        assert "changelog" in changelog.read_text(encoding="utf-8").casefold(), step


def test_didactic_notebooks_are_present() -> None:
    notebooks = sorted((ROOT / "notebooks").glob("*.ipynb"))
    assert len(notebooks) == 12
    for notebook in notebooks:
        source = notebook.read_text(encoding="utf-8")
        assert "from agent_harness" not in source
        assert "from steps" not in source
        parsed = nbformat.read(notebook, as_version=4)
        assert parsed.metadata["didactic_contract"]["extra_examples"] >= 2
        code_cells = [cell for cell in parsed.cells if cell.cell_type == "code"]
        assert len(code_cells) >= 5
        for index, cell in enumerate(parsed.cells):
            if cell.cell_type != "code":
                continue
            assert str(parsed.cells[index - 1].source).startswith(
                "### Spiegazione del blocco"
            )
            assert str(parsed.cells[index + 1].source).startswith("### Output atteso")
    for notebook in notebooks[:6]:
        source = notebook.read_text(encoding="utf-8")
        assert "ChatOpenAI" in source
        assert "create_agent" in source


def test_component_matrix_covers_article_mechanisms() -> None:
    matrix = (ROOT / "docs" / "HARNESS_COMPONENTS.md").read_text(encoding="utf-8").casefold()
    expected = {
        "prompt di sistema",
        "tool calling",
        "filesystem",
        "bash e codice",
        "browser",
        "mcp",
        "compaction",
        "offloading",
        "memoria",
        "skills",
        "pianificazione",
        "subagenti",
        "model routing",
        "human-in-the-loop",
        "continuation",
        "osservabilità",
        "audit",
    }
    assert all(component in matrix for component in expected)


def test_didactic_matrix_maps_every_final_backend_module() -> None:
    matrix = (ROOT / "docs" / "MATRICE_COPERTURA_DIDATTICA.md").read_text(
        encoding="utf-8"
    )
    modules = {
        path.name
        for path in (ROOT / "src" / "agent_harness").glob("*.py")
        if path.name != "__init__.py"
    }
    assert modules <= set(matrix.split("`"))
