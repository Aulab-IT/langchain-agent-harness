from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Mount point delle directory host dentro il container sandbox.
SANDBOX_WORKSPACE_MOUNT = "/workspace"
SANDBOX_SKILLS_MOUNT = "/skills"


class Settings(BaseSettings):
    """Configurazione validata, caricata da ambiente o file .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str | None = Field(default=None, repr=False)
    openai_model: str = "gpt-5.4-mini"
    openai_strong_model: str = "gpt-5.5"
    harness_context_window: int = Field(default=128_000, ge=1_000)

    harness_max_continuations: int = Field(default=3, ge=1, le=10)
    harness_eval_max_continuations: int = Field(default=1, ge=1, le=3)
    harness_max_tool_calls: int = Field(default=40, ge=1, le=200)
    harness_enable_rubric: bool = True
    harness_rubric_threshold: float = Field(default=0.7, ge=0, le=1)
    harness_enable_triggers: bool = False
    harness_trigger_tick_seconds: int = Field(default=30, ge=5, le=3600)
    harness_tool_output_limit: int = Field(default=12_000, ge=1_000, le=100_000)
    harness_enable_web_search: bool = True
    harness_enable_browser: bool = True
    harness_enable_mcp: bool = True
    harness_require_approval: bool = True
    harness_sandbox_image: str = "langchain-harness-sandbox:latest"
    # Rete Docker collegata a caldo, per comando e solo su conferma, quando l'agente
    # chiede accesso rete (docker_exec with_network=True). Revocata subito dopo.
    harness_sandbox_network: str = "bridge"
    harness_sandbox_idle_minutes: int = Field(default=30, ge=1, le=1_440)
    harness_sandbox_sweep_seconds: int = Field(default=60, ge=10, le=3_600)
    # Router fra modello di default e modello forte. Le parole chiave sono configurabili perché
    # dipendono dalla lingua e dal dominio: la lista di default è in middleware.py.
    harness_router_strong_keywords: str = ""
    harness_router_context_threshold: int = Field(default=40, ge=4, le=500)
    # Sorgente di skill-creator, la skill che insegna a scrivere skill conformi allo standard.
    # Configurabile perché l'harness non deve avere un URL di rete incastonato nel codice.
    harness_skill_creator_repo: str = "https://github.com/anthropics/skills"
    harness_skill_creator_subdir: str = "skills/skill-creator"
    # Base del registry Agent Skills usato per l'install per nome (adattatore in skills.py).
    skills_registry_url: str = "https://agentskills.io/registry"

    project_root: Path = PROJECT_ROOT

    @property
    def workspace_dir(self) -> Path:
        return (self.project_root / "workspace").resolve()

    @property
    def state_dir(self) -> Path:
        return (self.project_root / "state").resolve()

    @property
    def skills_dir(self) -> Path:
        return (self.project_root / "skills").resolve()

    def ensure_directories(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def require_openai_key(self) -> str:
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY non configurata. Copia .env.example in .env e aggiungi la chiave."
            )
        return self.openai_api_key
