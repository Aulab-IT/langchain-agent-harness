"""Configurazione provider modificabile da interfaccia (chiavi API + assegnazione gradini).

Le impostazioni di base arrivano da ambiente/.env in ``Settings``, immutabili per processo.
Questo modulo aggiunge un livello di override persistito su file, che l'utente edita dalla UI:
le chiavi API dei provider e, per ciascuno dei tre gradini, quale provider e quale modello
usare. Gli override sono un sottoinsieme dei campi di ``Settings`` (whitelist), applicati con
``model_copy`` sopra la configurazione corrente — così una chiave o un'assegnazione cambiata
dall'interfaccia vale al run successivo senza toccare ``.env`` né riavviare.

Invariante di sicurezza: le chiavi non escono mai in chiaro. Lo snapshot per la UI riporta solo
se una chiave è configurata, mai il suo valore.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_harness.config import Settings
from agent_harness.middleware import TIERS

OVERRIDES_FILE = "provider_overrides.json"


@dataclass(frozen=True)
class ProviderMeta:
    name: str
    label: str
    kind: str  # "cloud" | "local"
    key_field: str | None  # campo Settings della chiave API, None per i locali


PROVIDERS: dict[str, ProviderMeta] = {
    "openai": ProviderMeta("openai", "OpenAI", "cloud", "openai_api_key"),
    "anthropic": ProviderMeta("anthropic", "Claude (Anthropic)", "cloud", "anthropic_api_key"),
    "ollama": ProviderMeta("ollama", "Ollama (locale)", "local", None),
    "mlx": ProviderMeta("mlx", "MLX (locale)", "local", None),
}

KEY_FIELDS: tuple[str, ...] = ("openai_api_key", "anthropic_api_key")


def allowed_fields() -> set[str]:
    """I soli campi di ``Settings`` che la UI può sovrascrivere.

    Fuori da questo insieme nessun valore viene mai scritto negli override: impedisce che un
    payload dell'interfaccia riesca a toccare campi arbitrari della configurazione.
    """
    fields: set[str] = set(KEY_FIELDS)
    for tier in TIERS:
        fields.add(f"harness_provider_{tier}")
        for provider in PROVIDERS:
            fields.add(f"{provider}_model_{tier}")
    return fields


def load_overrides(state_dir: Path) -> dict[str, Any]:
    """Carica gli override persistiti, filtrati alla whitelist. File assente/corrotto → vuoto."""
    path = state_dir / OVERRIDES_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    allowed = allowed_fields()
    return {key: value for key, value in data.items() if key in allowed}


def save_overrides(state_dir: Path, overrides: dict[str, Any]) -> None:
    """Scrive gli override in modo atomico (tmp + replace), filtrati alla whitelist."""
    allowed = allowed_fields()
    clean = {key: value for key, value in overrides.items() if key in allowed}
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / OVERRIDES_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def apply_overrides(settings: Settings, overrides: dict[str, Any]) -> Settings:
    """Applica gli override sopra ``settings`` con ``model_copy``, senza rileggere l'ambiente.

    Non ricostruisce ``Settings`` da capo: rileggere ``.env`` perderebbe i campi non-ambiente
    (es. ``project_root``). ``model_copy`` non rivalida, quindi il provider dei gradini va
    validato prima, in :func:`validate_overrides`.
    """
    clean = {key: value for key, value in overrides.items() if key in allowed_fields()}
    if not clean:
        return settings
    return settings.model_copy(update=clean)


def tier_model(settings: Settings, tier: str) -> str:
    """Modello effettivo del gradino: dipende dal provider assegnato al gradino."""
    provider = getattr(settings, f"harness_provider_{tier}")
    return str(getattr(settings, f"{provider}_model_{tier}"))


def validate_overrides(settings: Settings) -> list[str]:
    """Verifica una configurazione già applicata; restituisce i problemi (vuoto = valida).

    Un gradino su provider cloud senza chiave, o senza modello, è un errore: meglio rifiutare
    il salvataggio che lasciare il run fallire a metà.
    """
    problems: list[str] = []
    for tier in TIERS:
        provider = getattr(settings, f"harness_provider_{tier}")
        meta = PROVIDERS.get(provider)
        if meta is None:
            problems.append(f"Gradino {tier}: provider sconosciuto '{provider}'.")
            continue
        model = tier_model(settings, tier)
        if not model:
            problems.append(f"Gradino {tier}: nessun modello impostato per {meta.label}.")
        if meta.key_field is not None and not getattr(settings, meta.key_field):
            problems.append(f"Gradino {tier}: {meta.label} richiede una chiave API mancante.")
    return problems


def snapshot(settings: Settings) -> dict[str, Any]:
    """Stato della configurazione provider per la UI. Nessuna chiave in chiaro."""
    return {
        "providers": [
            {
                "name": meta.name,
                "label": meta.label,
                "kind": meta.kind,
                "needs_key": meta.key_field is not None,
                "key_configured": (
                    True if meta.key_field is None else bool(getattr(settings, meta.key_field))
                ),
            }
            for meta in PROVIDERS.values()
        ],
        "tiers": [
            {
                "tier": tier,
                "provider": getattr(settings, f"harness_provider_{tier}"),
                "model": tier_model(settings, tier),
                "effort": getattr(settings, f"openai_effort_{tier}"),
            }
            for tier in TIERS
        ],
        "suggested_models": {
            provider: sorted(
                {
                    getattr(settings, f"{provider}_model_{tier}")
                    for tier in TIERS
                    if getattr(settings, f"{provider}_model_{tier}")
                }
            )
            for provider in PROVIDERS
        },
    }


def merge_key_change(overrides: dict[str, Any], field: str, value: str | None) -> None:
    """Applica una modifica a un campo chiave nel dizionario override, in place.

    ``None`` = lascia invariato (l'utente non ha toccato il campo); stringa vuota = azzera la
    chiave (nessuna chiave); valore = imposta. Lo stato azzerato resta esplicito negli override
    (stringa vuota), così ``apply_overrides`` lo raggiunge sempre con ``model_copy`` senza dover
    tracciare una configurazione di base separata.
    """
    if value is None:
        return
    overrides[field] = value
