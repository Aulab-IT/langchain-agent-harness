from __future__ import annotations

from pathlib import Path

from agent_harness import provider_settings as pc
from agent_harness.config import Settings


def _settings(tmp_path: Path, **kw: object) -> Settings:
    return Settings(_env_file=None, project_root=tmp_path, **kw)


def test_snapshot_hides_keys_and_lists_tiers(tmp_path: Path) -> None:
    settings = _settings(tmp_path, openai_api_key="sk-secret")
    snap = pc.snapshot(settings)
    # Nessuna chiave in chiaro, solo presenza.
    dumped = str(snap)
    assert "sk-secret" not in dumped
    openai = next(p for p in snap["providers"] if p["name"] == "openai")
    assert openai["key_configured"] is True
    anthropic = next(p for p in snap["providers"] if p["name"] == "anthropic")
    assert anthropic["key_configured"] is False
    assert [t["tier"] for t in snap["tiers"]] == ["low", "mid", "high"]
    assert snap["tiers"][0]["provider"] == "openai"


def test_apply_overrides_reassigns_tier_provider_and_model(tmp_path: Path) -> None:
    settings = _settings(tmp_path, openai_api_key="sk")
    overrides = {"harness_provider_low": "ollama", "ollama_model_low": "qwen3:8b"}
    updated = pc.apply_overrides(settings, overrides)
    assert updated.harness_provider_low == "ollama"
    assert pc.tier_model(updated, "low") == "qwen3:8b"
    # project_root preservato (non si rilegge l'ambiente).
    assert updated.project_root == tmp_path


def test_validate_flags_cloud_tier_without_key(tmp_path: Path) -> None:
    settings = _settings(tmp_path, openai_api_key=None)  # gradini openai, nessuna chiave
    problems = pc.validate_overrides(settings)
    assert len(problems) == 3
    assert all("chiave" in p.lower() for p in problems)


def test_validate_flags_missing_model(tmp_path: Path) -> None:
    settings = _settings(tmp_path, harness_provider_high="mlx", mlx_model_high="")
    problems = pc.validate_overrides(settings)
    assert any("modello" in p.lower() and "high" in p for p in problems)


def test_local_tiers_need_no_key(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        harness_provider_low="ollama",
        harness_provider_mid="ollama",
        harness_provider_high="ollama",
    )
    assert pc.validate_overrides(settings) == []


def test_merge_key_change_semantics() -> None:
    ov: dict[str, object] = {"openai_api_key": "old"}
    pc.merge_key_change(ov, "openai_api_key", None)  # lascia
    assert ov["openai_api_key"] == "old"
    pc.merge_key_change(ov, "openai_api_key", "new")  # imposta
    assert ov["openai_api_key"] == "new"
    pc.merge_key_change(ov, "openai_api_key", "")  # azzera (esplicito)
    assert ov["openai_api_key"] == ""


def test_overrides_roundtrip_and_whitelist(tmp_path: Path) -> None:
    state = tmp_path / "state"
    overrides = {
        "anthropic_api_key": "ak",
        "harness_provider_high": "anthropic",
        "not_allowed_field": "danger",  # deve essere scartato
    }
    pc.save_overrides(state, overrides)
    loaded = pc.load_overrides(state)
    assert loaded == {"anthropic_api_key": "ak", "harness_provider_high": "anthropic"}


def test_parse_model_ids_from_openai_shape() -> None:
    data = {"object": "list", "data": [
        {"id": "qwen3:8b", "object": "model"},
        {"id": "gemma3:4b"},
        {"nope": "x"},  # senza id → scartato
    ]}
    assert pc._parse_model_ids(data) == ["gemma3:4b", "qwen3:8b"]
    assert pc._parse_model_ids({}) == []
    assert pc._parse_model_ids("junk") == []


async def test_list_local_models_ignores_non_local(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    result = await pc.list_local_models(settings, "openai")
    assert result == {"running": False, "models": []}


async def test_list_local_models_offline_port(tmp_path: Path) -> None:
    # Porta quasi certamente chiusa → running False, nessun errore.
    settings = _settings(tmp_path, ollama_base_url="http://127.0.0.1:1/v1")
    result = await pc.list_local_models(settings, "ollama")
    assert result == {"running": False, "models": []}


def test_snapshot_includes_runtime_flags(tmp_path: Path) -> None:
    settings = _settings(tmp_path, harness_enable_rubric=False, harness_enable_web_search=True)
    flags = pc.snapshot(settings)["flags"]
    assert flags["rubric"] is False
    assert flags["web_search"] is True
    assert set(flags) == {"web_search", "browser", "mcp", "rubric"}


def test_flag_fields_are_whitelisted(tmp_path: Path) -> None:
    allowed = pc.allowed_fields()
    for field in pc.FLAG_FIELDS.values():
        assert field in allowed


def test_apply_flag_override(tmp_path: Path) -> None:
    settings = _settings(tmp_path, harness_enable_mcp=True)
    updated = pc.apply_overrides(settings, {"harness_enable_mcp": False})
    assert updated.harness_enable_mcp is False
