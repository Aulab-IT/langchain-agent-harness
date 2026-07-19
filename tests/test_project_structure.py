from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
