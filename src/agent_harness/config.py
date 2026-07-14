from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Serializza le operazioni sull'albero `skills/` condiviso: la copia verso le radici di
# sessione (`control_store.prepare_session_root`) e le scritture dei tool skill_* e delle
# rotte REST (`skills.py`). Sta qui perché è l'unico modulo che entrambi importano.
SKILLS_LOCK = threading.RLock()
SUBAGENTS_LOCK = threading.RLock()

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
    # Scala a tre gradini. Modello e reasoning effort salgono insieme: un modello caro che
    # ragiona poco paga il prezzo alto senza comprarne il beneficio, e la coppia inversa
    # spende reasoning su un modello che non lo sfrutta. Tenerli agganciati rende il costo
    # monotono lungo la scala, che è la sola proprietà che permette di dire «sali solo se serve».
    openai_model_low: str = "gpt-5.6-luna"
    openai_model_mid: str = "gpt-5.6-terra"
    openai_model_high: str = "gpt-5.6-sol"
    openai_effort_low: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"
    openai_effort_mid: Literal["none", "low", "medium", "high", "xhigh", "max"] = "medium"
    openai_effort_high: Literal["none", "low", "medium", "high", "xhigh", "max"] = "high"
    # Dollari per milione di token, input e output. Stanno accanto al nome del modello perché
    # chi cambia l'uno deve cambiare l'altro: un prezzo che resta indietro non fa rumore, si
    # limita a mentire nel tooltip finché non arriva la fattura.
    openai_price_in_low: float = Field(default=1.0, ge=0)
    openai_price_out_low: float = Field(default=6.0, ge=0)
    openai_price_in_mid: float = Field(default=2.5, ge=0)
    openai_price_out_mid: float = Field(default=15.0, ge=0)
    openai_price_in_high: float = Field(default=5.0, ge=0)
    openai_price_out_high: float = Field(default=30.0, ge=0)

    # Provider per gradino. Ogni gradino sceglie il vendor: openai (default), anthropic
    # (Claude), oppure un provider locale (ollama, mlx). Così si può, per esempio, tenere il
    # gradino basso in locale e i due alti su Claude/OpenAI, senza toccare il codice.
    harness_provider_low: Literal["openai", "anthropic", "ollama", "mlx"] = "openai"
    harness_provider_mid: Literal["openai", "anthropic", "ollama", "mlx"] = "openai"
    harness_provider_high: Literal["openai", "anthropic", "ollama", "mlx"] = "openai"

    # Claude (Anthropic). Chiave separata da OpenAI; id modello e prezzi per gradino, come
    # per OpenAI il prezzo sta accanto al modello perché vanno cambiati insieme.
    anthropic_api_key: str | None = Field(default=None, repr=False)
    anthropic_model_low: str = "claude-haiku-4-5"
    anthropic_model_mid: str = "claude-sonnet-5"
    anthropic_model_high: str = "claude-opus-4-8"
    anthropic_price_in_low: float = Field(default=1.0, ge=0)
    anthropic_price_out_low: float = Field(default=5.0, ge=0)
    anthropic_price_in_mid: float = Field(default=3.0, ge=0)
    anthropic_price_out_mid: float = Field(default=15.0, ge=0)
    anthropic_price_in_high: float = Field(default=5.0, ge=0)
    anthropic_price_out_high: float = Field(default=25.0, ge=0)

    # Provider locali. Nessuna fattura API (prezzo zero); l'endpoint è OpenAI-compatibile.
    # Un modello vuoto significa "gradino non mappato su questo provider".
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model_low: str = "qwen3:8b"
    ollama_model_mid: str = "qwen3:14b"
    ollama_model_high: str = "qwen3:14b"
    mlx_base_url: str = "http://127.0.0.1:8080/v1"
    mlx_model_low: str = ""
    mlx_model_mid: str = ""
    mlx_model_high: str = ""

    harness_context_window: int = Field(default=128_000, ge=1_000)
    # Budget di contesto realmente applicato (Fase 1): la finestra utile è
    # `harness_context_window - harness_reserved_output_tokens`; oltre `warning` si segnala,
    # oltre `compaction` si riduce. Prima `harness_context_window` era solo un metadato in UI.
    harness_reserved_output_tokens: int = Field(default=4_000, ge=0, le=64_000)
    harness_context_warning_ratio: float = Field(default=0.7, ge=0.1, le=1.0)
    harness_context_compaction_ratio: float = Field(default=0.8, ge=0.1, le=1.0)
    # Governance costo P1. Questi sono limiti cumulativi dell'intero run: includono agente
    # principale, router, grader e subagent. Le prenotazioni pre-call impediscono alle chiamate
    # parallele di superare insieme il residuo disponibile.
    harness_max_run_tokens: int = Field(default=500_000, ge=1_000, le=10_000_000)
    harness_max_run_cost_usd: float = Field(default=3.0, ge=0.0, le=10_000.0)
    harness_max_run_seconds: int = Field(default=900, ge=10, le=86_400)
    harness_max_model_calls: int = Field(default=48, ge=1, le=1_000)
    harness_max_subagent_calls: int = Field(default=10, ge=0, le=200)
    # Guardrail per singola delega: un subagent bloccato non può assorbire da solo tutto il
    # budget globale continuando a reinviare lo stesso contesto.
    harness_max_subagent_model_calls: int = Field(default=10, ge=1, le=200)
    harness_max_subagent_tokens: int = Field(default=200_000, ge=1_000, le=10_000_000)
    harness_budget_warning_ratio: float = Field(default=0.7, ge=0.1, le=1.0)
    # Qualunque ToolMessage oltre questa soglia viene salvato nel workspace e sostituito nel
    # prompt da riferimento, checksum ed estratto. Il contenuto resta recuperabile.
    harness_context_tool_output_tokens: int = Field(default=2_000, ge=100, le=100_000)
    harness_subagent_result_max_chars: int = Field(default=4_000, ge=500, le=50_000)

    # La memoria (`memories/AGENTS.md`) entra nel prompt a ogni run: se cresce senza limite, il
    # costo del prompt cresce con lei per sempre. L'agente può scriverci; questo cap frena la
    # crescita incontrollata. Generoso (~8k token) così scatta di rado, e quando scatta è
    # visibile con un evento invece che silenzioso.
    harness_memory_max_chars: int = Field(default=32_000, ge=1_000, le=200_000)

    harness_max_continuations: int = Field(default=3, ge=1, le=10)
    harness_eval_max_continuations: int = Field(default=1, ge=1, le=3)
    harness_max_tool_calls: int = Field(default=56, ge=1, le=200)
    # Limite deleghe `task`: preserva parallelismo, evita picchi costo/rate limit.
    harness_subagents_max_parallel: int = Field(default=4, ge=1, le=32)
    # Planner semantico: confronta l'obiettivo con il roster dinamico una volta per run.
    # Fallisce aperto sul routing nativo del tool `task`, quindi non blocca l'esecuzione.
    harness_enable_subagent_routing: bool = True
    harness_subagent_router_max_tasks: int = Field(default=8, ge=1, le=16)
    # Probe reale prima del run: evita che modello inesistente emerga dopo tool/deleghe.
    # Successi in cache riducono latenza/costo; cambio nome/provider genera chiave diversa.
    harness_model_preflight_timeout_seconds: int = Field(default=20, ge=2, le=120)
    harness_model_preflight_ttl_seconds: int = Field(default=300, ge=0, le=86_400)
    harness_enable_rubric: bool = True
    # Due domande diverse, due soglie. «L'obiettivo è raggiunto?» resta severa: sotto 0.7 si
    # riprova. «Il gradino ha fallito?» dev'essere più esigente, perché da quando il router fa
    # escalation ogni bocciatura compra un modello più caro. Misurato: sull'eval set le
    # risposte corrette prendono da 0.61 in su; una risposta mediocre oscilla fra 0.37 e 0.57
    # a seconda del giro. A 0.7 il router avrebbe pagato il gradino superiore su 3 risposte
    # giuste su 16. Sotto 0.5 ci finiscono solo i fallimenti netti e le violazioni di sicurezza,
    # che il veto porta a 0. Vedi `evals/calibrate_grader.py`.
    harness_rubric_threshold: float = Field(default=0.7, ge=0, le=1)
    harness_escalation_threshold: float = Field(default=0.5, ge=0, le=1)
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
    # Nessuna impostazione per il router: non predice più la difficoltà da parole chiave, sale
    # di un gradino quando il grader boccia l'iterazione. Vedi `middleware.TierLadder`.
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

    @property
    def subagents_dir(self) -> Path:
        return (self.project_root / "subagents").resolve()

    def ensure_directories(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.subagents_dir.mkdir(parents=True, exist_ok=True)

    def require_openai_key(self) -> str:
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY non configurata. Copia .env.example in .env e aggiungi la chiave."
            )
        return self.openai_api_key

    def require_anthropic_key(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY non configurata. Serve per i gradini su provider 'anthropic'."
            )
        return self.anthropic_api_key

    def uses_provider(self, provider: str) -> bool:
        """True se almeno un gradino è mappato su questo provider."""
        return provider in {
            self.harness_provider_low,
            self.harness_provider_mid,
            self.harness_provider_high,
        }
