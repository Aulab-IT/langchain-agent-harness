from pathlib import Path

import pytest

from agent_harness.config import Settings


def test_settings_create_expected_paths(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, project_root=tmp_path)
    settings.ensure_directories()
    assert settings.workspace_dir == (tmp_path / "workspace").resolve()
    assert settings.workspace_dir.is_dir()
    assert settings.state_dir.is_dir()


def test_openai_key_is_required_explicitly(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, project_root=tmp_path, openai_api_key=None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        settings.require_openai_key()


def test_limits_are_validated(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, project_root=tmp_path, harness_max_continuations=0)

