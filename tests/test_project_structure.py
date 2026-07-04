from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_increment_has_code_and_guide() -> None:
    steps = sorted(
        path
        for path in (ROOT / "steps").iterdir()
        if path.is_dir() and path.name[:2].isdigit()
    )
    assert [path.name[:2] for path in steps] == [f"{index:02d}" for index in range(14)]
    for step in steps:
        assert (step / "app.py").is_file(), step
        guide = step / "GUIDA.md"
        assert guide.is_file(), step
        assert len(guide.read_text(encoding="utf-8").split()) >= 100, step


def test_didactic_notebooks_are_present() -> None:
    notebooks = sorted((ROOT / "notebooks").glob("*.ipynb"))
    assert len(notebooks) == 6
    for notebook in notebooks:
        source = notebook.read_text(encoding="utf-8")
        assert "ChatOpenAI" in source
        assert "create_agent" in source
        assert "from agent_harness" not in source
        assert "from steps" not in source


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
