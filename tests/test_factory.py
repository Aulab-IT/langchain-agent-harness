from pathlib import Path

import pytest

from agent_harness.config import Settings
from agent_harness.factory import build_harness, build_workspace_permissions


def test_workspace_permissions_include_directory_roots() -> None:
    permissions = build_workspace_permissions()
    allowed_paths = {
        path
        for permission in permissions
        if permission.mode == "allow"
        for path in permission.paths
    }

    assert {"/workspace", "/workspace/**", "/memories", "/skills"} <= allowed_paths


@pytest.mark.asyncio
async def test_factory_builds_graph_without_network_calls(tmp_path: Path) -> None:
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "AGENTS.md").write_text("# Memoria\n", encoding="utf-8")
    (tmp_path / "skills").mkdir()
    settings = Settings(
        _env_file=None,
        project_root=tmp_path,
        openai_api_key="test-key",
        harness_enable_mcp=False,
        harness_enable_web_search=False,
        harness_require_approval=False,
    )
    async with build_harness(settings) as harness:
        assert harness.graph is not None
        assert {"docker_exec", "current_utc_time"} <= {tool.name for tool in harness.tools}
        assert (tmp_path / "state" / "checkpoints.sqlite").exists()
