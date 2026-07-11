import json
from pathlib import Path

import pytest

from agent_harness.config import Settings
from agent_harness.factory import (
    build_harness,
    build_tier_models,
    build_workspace_permissions,
    tier_spec,
)
from agent_harness.improve import overrides_fingerprint


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


@pytest.mark.asyncio
async def test_factory_exposes_canary_attribution(tmp_path: Path) -> None:
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "AGENTS.md").write_text("# Memoria\n", encoding="utf-8")
    (tmp_path / "skills").mkdir()
    (tmp_path / "state").mkdir()
    candidate = {"harness_max_tool_calls": 12}
    (tmp_path / "state" / "canary.json").write_text(
        json.dumps(
            {
                "source": "proposal.md",
                "fraction": 1.0,
                "overrides": candidate,
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        project_root=tmp_path,
        openai_api_key="test-key",
        harness_enable_mcp=False,
        harness_enable_web_search=False,
        harness_require_approval=False,
    )
    events: list[dict[str, object]] = []

    async with build_harness(
        settings,
        session_id="canary-session",
        event_callback=events.append,
    ) as harness:
        assert harness.config_arm == "canary"
        assert harness.config_source == "proposal.md"
        assert harness.config_fingerprint == overrides_fingerprint(candidate)
        assert harness.baseline_fingerprint == overrides_fingerprint({})
    selected = next(event for event in events if event["type"] == "config.selected")
    assert selected["arm"] == "canary"
    assert selected["source"] == "proposal.md"


def test_tier_can_target_claude_and_local(tmp_path: Path) -> None:
    # Gradino basso in locale (Ollama, nessuna chiave), alto su Claude.
    settings = Settings(
        _env_file=None,
        project_root=tmp_path,
        openai_api_key="test-openai",
        anthropic_api_key="test-anthropic",
        harness_provider_low="ollama",
        harness_provider_mid="openai",
        harness_provider_high="anthropic",
    )
    assert tier_spec(settings, "low").provider == "ollama"
    assert tier_spec(settings, "high").name == settings.anthropic_model_high
    # Locale non ha prezzo API.
    assert tier_spec(settings, "low").price_in == 0.0

    models = build_tier_models(settings)
    assert set(models) == {"low", "mid", "high"}
    assert models["high"].name == "claude-opus-4-8"


def test_all_local_config_needs_no_cloud_key(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        project_root=tmp_path,
        harness_provider_low="ollama",
        harness_provider_mid="ollama",
        harness_provider_high="ollama",
    )
    # Nessuna OPENAI/ANTHROPIC key, ma tutti i gradini locali: deve costruire lo stesso.
    models = build_tier_models(settings)
    assert models["low"].model is not None


def test_anthropic_tier_without_key_raises(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        project_root=tmp_path,
        harness_provider_high="anthropic",
        openai_api_key="test-openai",
    )
    with pytest.raises(RuntimeError):
        build_tier_models(settings)
