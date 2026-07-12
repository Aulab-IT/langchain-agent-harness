"""Configurazione dei server MCP esterni, editabile dall'utente come ``state/mcp.json``.

Formato standard ``mcpServers`` (lo stesso di Claude Desktop, Cursor e gli altri client): un
oggetto le cui chiavi sono i nomi dei server e i cui valori descrivono come raggiungerli. Uno
stdio porta ``command``/``args``/``env``; un server remoto porta ``url`` e un ``transport``
(``sse`` o ``streamable_http``). Questo modulo è logica pura — parsing, validazione, merge ed
espansione dei segreti — così è interamente testabile senza rete e senza avviare un processo.

Tre invarianti:

- **il server interno non è sovrascrivibile**: ``local_harness`` (skill_*, glossario) è sempre
  presente e il suo nome è riservato; un utente non può rimpiazzarlo con un proprio processo;
- **i segreti non stanno nel file**: i valori possono contenere ``${VAR}``, espansi
  dall'ambiente al momento del load. Nel JSON resta il riferimento, non la chiave;
- **un server malformato non rompe gli altri**: la validazione scarta le voci non valide e
  restituisce i problemi come lista, invece di sollevare e far fallire l'intero load.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MCP_CONFIG_FILE = "mcp.json"

# Nome del server interno: sempre montato, mai sovrascrivibile da configurazione utente.
BUILTIN_SERVER = "local_harness"

# Transport ammessi per i server remoti. `stdio` è implicito per le voci con `command`.
_REMOTE_TRANSPORTS = ("sse", "streamable_http")

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class MCPValidation:
    """Esito della validazione: connessioni pronte per il client e problemi leggibili."""

    connections: dict[str, dict[str, Any]]
    problems: list[str]


def builtin_connection(session_root: Path, skills_dir: Path) -> dict[str, Any]:
    """Il server interno stdio, con l'ambiente che gli fa sincronizzare le skill nella sessione."""
    env = {
        **os.environ,
        "HARNESS_SESSION_ROOT": str(session_root),
        "HARNESS_SKILLS_DIR": str(skills_dir),
    }
    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "agent_harness.mcp_server"],
        "env": env,
    }


def expand_env(value: Any) -> Any:
    """Espande ricorsivamente ``${VAR}`` nelle stringhe usando l'ambiente del processo.

    Una variabile non definita resta come riferimento letterale (``${VAR}``) invece di
    diventare stringa vuota: così un segreto mancante è visibile come errore di connessione,
    non silenziosamente ridotto a nulla.
    """
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    return value


def _normalize_server(name: str, spec: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Porta una voce grezza al formato connessione del client, o spiega perché non è valida."""
    if not isinstance(spec, dict):
        return None, f"Server '{name}': la definizione deve essere un oggetto."
    if name == BUILTIN_SERVER:
        return None, f"Server '{name}': nome riservato al server interno, scegline un altro."

    command = spec.get("command")
    url = spec.get("url")
    if command and url:
        return None, f"Server '{name}': specifica 'command' (stdio) oppure 'url', non entrambi."

    if command:
        if not isinstance(command, str):
            return None, f"Server '{name}': 'command' deve essere una stringa."
        connection: dict[str, Any] = {"transport": "stdio", "command": command}
        args = spec.get("args", [])
        if not isinstance(args, list):
            return None, f"Server '{name}': 'args' deve essere una lista."
        connection["args"] = [str(arg) for arg in args]
        env = spec.get("env", {})
        if env:
            if not isinstance(env, dict):
                return None, f"Server '{name}': 'env' deve essere un oggetto."
            # L'ambiente del figlio parte da quello del processo, così un server stdio trova
            # PATH e interprete; sopra vanno le variabili dichiarate (segreti espansi inclusi).
            connection["env"] = {**os.environ, **{str(k): str(v) for k, v in env.items()}}
        return connection, None

    if url:
        if not isinstance(url, str):
            return None, f"Server '{name}': 'url' deve essere una stringa."
        transport = spec.get("transport", "streamable_http")
        if transport not in _REMOTE_TRANSPORTS:
            return None, (
                f"Server '{name}': transport '{transport}' non valido "
                f"(ammessi: {', '.join(_REMOTE_TRANSPORTS)})."
            )
        connection = {"transport": transport, "url": url}
        headers = spec.get("headers")
        if headers is not None:
            if not isinstance(headers, dict):
                return None, f"Server '{name}': 'headers' deve essere un oggetto."
            connection["headers"] = {str(k): str(v) for k, v in headers.items()}
        return connection, None

    return None, f"Server '{name}': manca 'command' (stdio) o 'url' (remoto)."


def validate_user_config(raw: Any) -> MCPValidation:
    """Valida il documento ``mcp.json`` grezzo, espandendo i segreti e scartando le voci rotte."""
    problems: list[str] = []
    connections: dict[str, dict[str, Any]] = {}
    if raw in (None, "", {}):
        return MCPValidation(connections, problems)
    if not isinstance(raw, dict):
        return MCPValidation(connections, ["Il documento MCP deve essere un oggetto JSON."])
    servers = raw.get("mcpServers", raw)
    if not isinstance(servers, dict):
        return MCPValidation(connections, ["La chiave 'mcpServers' deve essere un oggetto."])
    for name, spec in servers.items():
        connection, problem = _normalize_server(str(name), expand_env(spec))
        if problem is not None:
            problems.append(problem)
            continue
        if connection is not None:
            connections[str(name)] = connection
    return MCPValidation(connections, problems)


def load_user_config_text(state_dir: Path) -> str:
    """Il testo grezzo di ``state/mcp.json`` per l'editor della UI. Assente → template vuoto."""
    path = state_dir / MCP_CONFIG_FILE
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""
    return json.dumps({"mcpServers": {}}, ensure_ascii=False, indent=2)


def load_user_validation(state_dir: Path) -> MCPValidation:
    """Carica e valida ``state/mcp.json``. File assente/corrotto → nessun server, nessun errore."""
    path = state_dir / MCP_CONFIG_FILE
    if not path.is_file():
        return MCPValidation({}, [])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return MCPValidation({}, [f"mcp.json non leggibile: {exc}"])
    return validate_user_config(raw)


def save_user_config(state_dir: Path, text: str) -> MCPValidation:
    """Valida il testo e, se non ci sono errori di forma, lo scrive in modo atomico.

    Restituisce la validazione: se ``problems`` non è vuoto il file NON viene scritto, così
    una configurazione rotta non arriva mai al prossimo run.
    """
    try:
        raw = json.loads(text) if text.strip() else {"mcpServers": {}}
    except json.JSONDecodeError as exc:
        return MCPValidation({}, [f"JSON non valido: {exc}"])
    validation = validate_user_config(raw)
    if validation.problems:
        return validation
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / MCP_CONFIG_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return validation


def user_connections(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Solo i server MCP **esterni** validi (nessun server interno).

    Il server interno ``local_harness`` non gira più come subprocess: i suoi tool sono
    in-process (vedi ``builtin_tools``). Qui restano i server aggiunti dall'utente, che vivono
    fuori processo perché è lì che l'isolamento ha senso.
    """
    return dict(load_user_validation(state_dir).connections)


def merged_connections(
    state_dir: Path, session_root: Path, skills_dir: Path
) -> dict[str, dict[str, Any]]:
    """Server interno più server utente validi. Il server interno vince sempre sul nome.

    Mantenuto per compatibilità e per il probe che mostra anche il built-in; il percorso di
    run usa ``user_connections`` più i tool interni in-process.
    """
    connections = user_connections(state_dir)
    connections[BUILTIN_SERVER] = builtin_connection(session_root, skills_dir)
    return connections


__all__ = [
    "BUILTIN_SERVER",
    "MCP_CONFIG_FILE",
    "MCPValidation",
    "builtin_connection",
    "expand_env",
    "load_user_config_text",
    "load_user_validation",
    "merged_connections",
    "save_user_config",
    "user_connections",
    "validate_user_config",
]
