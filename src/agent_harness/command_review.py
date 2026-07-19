"""Classificazione statica dei comandi sottoposti ad approvazione.

Lo scopo è mettere l'utente in condizione di capire *cosa fa* un comando prima di
approvarlo. La classificazione è deliberatamente statica e conservativa: non chiediamo a
un modello di riassumere il comando, perché la spiegazione fa parte di un controllo di
sicurezza e un riassunto generato dallo stesso agente che ha proposto il comando sarebbe
influenzabile dal contenuto che l'agente ha letto durante il run.

Questo modulo NON è un confine di sicurezza. È un aiuto alla lettura: un comando può
eludere il riconoscimento (variabili di shell, sostituzioni di comando, offuscamento) e
comunque fare ciò che vuole. Il vero confine resta il container e la conferma dell'utente.
Per questo, quando il parsing non è affidabile lo diciamo invece di tacere.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass, field
from typing import Any

# Un comando può essere una pipeline o una sequenza. Spezziamo sugli operatori di shell
# per esaminare il primo token (il programma) di ogni segmento.
_SEGMENT_SEPARATOR = re.compile(r"\|\||&&|[;|\n&]")
# Tetto sul comando mostrato: il dialogo di approvazione deve restare leggibile, e un
# comando più lungo di così va comunque letto nella trace, non in un modale.
_MAX_COMMAND_CHARS = 4_000

# Prefissi che non sono il programma reale, ma lo introducono.
_TRANSPARENT_PREFIXES = {"sudo", "env", "time", "nohup", "exec", "command", "nice", "xargs"}

_INSTALLERS = {
    "pip", "pip3", "uv", "npm", "pnpm", "yarn",
    "apt", "apt-get", "poetry", "cargo", "gem", "brew",
}
_DELETERS = {"rm", "rmdir", "unlink", "shred", "truncate"}
_NETWORK = {"curl", "wget", "ssh", "scp", "nc", "netcat", "ftp", "telnet", "rsync"}
_INTERPRETERS = {"python", "python3", "node", "sh", "bash", "zsh", "ruby", "perl", "php"}
_TESTERS = {"pytest", "tox", "unittest", "vitest", "jest", "go"}
_READERS = {"cat", "ls", "head", "tail", "grep", "rg", "find", "wc", "stat", "file", "diff", "less"}
_WRITERS = {"touch", "mkdir", "cp", "mv", "tee", "sed", "install", "chmod", "chown", "ln"}

_CATEGORY_LABELS = {
    "install": "Installazione pacchetti",
    "delete": "Cancellazione file",
    "network": "Accesso rete",
    "execute": "Esecuzione codice",
    "test": "Esecuzione test",
    "read": "Lettura file",
    "write": "Scrittura file",
    "vcs": "Controllo versione",
    "unknown": "Comando non riconosciuto",
}

# Percorsi assoluti e percorsi relativi con estensione. Non risolviamo nulla: mostriamo
# ciò che compare testualmente, perché è quello che l'utente deve poter riconoscere.
_PATH_PATTERN = re.compile(r"(?<![\w-])(/[\w./-]+|\.{1,2}/[\w./-]+|[\w.-]+/[\w./-]+)")
_REDIRECT_PATTERN = re.compile(r">>?\s*([\w./-]+)")
# Gli URL contengono barre ma non sono percorsi del filesystem: vanno tolti prima della
# scansione, altrimenti `https://host/a.sh` finirebbe fra i percorsi come `//host/a.sh`.
_URL_PATTERN = re.compile(r"\b[a-zA-Z][\w+.-]*://\S+")


@dataclass(frozen=True)
class CommandReview:
    """Cosa mostriamo accanto al comando nel dialogo di approvazione."""

    categories: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parsed: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _segments(command: str) -> list[str]:
    return [part.strip() for part in _SEGMENT_SEPARATOR.split(command) if part.strip()]


def _program(segment: str) -> str | None:
    """Primo token del segmento, saltando prefissi trasparenti e assegnazioni VAR=x."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return None
    for token in tokens:
        if "=" in token and not token.startswith("-") and "/" not in token.split("=", 1)[0]:
            continue  # assegnazione di variabile d'ambiente
        base = token.rsplit("/", 1)[-1]
        if base in _TRANSPARENT_PREFIXES:
            continue
        return base
    return None


def _categorize(program: str, segment: str) -> str:
    if program in _INSTALLERS and re.search(r"\b(install|add|sync)\b", segment):
        return "install"
    if program in _DELETERS:
        return "delete"
    if program in _NETWORK:
        return "network"
    if program in _TESTERS or re.search(r"\b(npm|pnpm|yarn)\s+(run\s+)?test\b", segment):
        return "test"
    if program == "git":
        return "vcs"
    if program in _INTERPRETERS:
        return "execute"
    if program in _WRITERS:
        return "write"
    if program in _READERS:
        return "read"
    return "unknown"


def _collect_paths(command: str) -> list[str]:
    found: list[str] = []
    command = _URL_PATTERN.sub(" ", command)
    for match in _PATH_PATTERN.finditer(command):
        candidate = match.group(1)
        if candidate not in found:
            found.append(candidate)
    for match in _REDIRECT_PATTERN.finditer(command):
        candidate = match.group(1)
        if candidate not in found:
            found.append(candidate)
    return found[:12]


_FORCE_DELETE = re.compile(
    r"\brm\b[^|;&]*\s-[a-zA-Z]*[rR][a-zA-Z]*f|\brm\b[^|;&]*\s-[a-zA-Z]*f[a-zA-Z]*[rR]"
)


def _collect_warnings(command: str, categories: set[str]) -> list[str]:
    warnings: list[str] = []
    if _FORCE_DELETE.search(command):
        warnings.append(
            "Cancellazione ricorsiva e forzata: i file eliminati non sono recuperabili."
        )
    if re.search(r"\bsudo\b", command):
        warnings.append("Richiede privilegi di root dentro il container.")
    if re.search(r"\bchmod\b[^|;&]*\b777\b", command):
        warnings.append("Rende un percorso scrivibile da chiunque.")
    if re.search(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|python3?)\b", command):
        warnings.append(
            "Scarica ed esegue codice remoto in un solo passaggio: il contenuto non è "
            "ispezionabile prima dell'esecuzione."
        )
    if re.search(r"\$\(|`", command):
        warnings.append(
            "Contiene una sostituzione di comando: ciò che viene eseguito dipende "
            "dall'output di un altro comando, quindi non è del tutto leggibile qui."
        )
    if re.search(r">\s*/(?!workspace)", command):
        warnings.append("Scrive fuori da /workspace, dove il filesystem è di sola lettura.")
    if "unknown" in categories:
        warnings.append("Almeno un comando non è stato riconosciuto: leggilo per intero.")
    return warnings


def payload_wants_network(value: Any) -> bool:
    """True se una delle tool call in sospeso chiede accesso rete (``with_network``)."""
    if isinstance(value, dict):
        if value.get("with_network") is True:
            return True
        return any(payload_wants_network(nested) for nested in value.values())
    if isinstance(value, list):
        return any(payload_wants_network(nested) for nested in value)
    return False


def extract_command(value: Any) -> str | None:
    """Primo ``command`` trovato nel payload di interrupt, a qualsiasi profondità."""
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str):
            return command[:_MAX_COMMAND_CHARS]
        for nested in value.values():
            found = extract_command(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = extract_command(nested)
            if found:
                return found
    return None


def build_approval_summary(payload: Any) -> dict[str, Any]:
    """Ciò che l'utente vede prima di approvare, ricostruito dal payload grezzo.

    Vive qui, e non nel control plane, perché ogni superficie di approvazione — CLI e
    Control Center — deve mostrare le stesse informazioni. Quando questa logica stava solo
    lato web, chi approvava da terminale decideva senza la classificazione del comando: la
    stessa decisione di sicurezza presa con meno elementi.

    Il payload grezzo non viene mai inoltrato: si estraggono i soli campi che servono a
    decidere.
    """
    is_network = payload_wants_network(payload)
    action = "docker_exec"
    if isinstance(payload, dict):
        action = str(payload.get("action", action))
    summary: dict[str, Any] = {
        "action": action,
        "description": (
            "Accesso rete temporaneo alla sandbox Docker (per questo comando)"
            if is_network
            else "Esecuzione comando in sandbox Docker isolata"
        ),
    }
    if is_network:
        summary["network"] = True
    command = extract_command(payload)
    if command:
        summary["command"] = command
        # Classificazione statica: dice all'utente cosa fa il comando prima che lo approvi.
        # Non è un'autorizzazione, è una spiegazione.
        summary["review"] = review_command(command).as_dict()
    return summary


def review_command(command: str) -> CommandReview:
    """Classifica un comando shell per la revisione umana. Mai usato come autorizzazione."""
    text = (command or "").strip()
    if not text:
        return CommandReview(parsed=False, warnings=["Comando vuoto o non disponibile."])

    categories: list[str] = []
    parsed = True
    for segment in _segments(text):
        program = _program(segment)
        if program is None:
            parsed = False
            continue
        category = _categorize(program, segment)
        if category not in categories:
            categories.append(category)

    if re.search(r">>?\s*[\w./-]+", text) and "write" not in categories:
        categories.append("write")
    if not categories:
        categories.append("unknown")
        parsed = False

    warnings = _collect_warnings(text, set(categories))
    if not parsed:
        warnings.append("Il comando non è interamente analizzabile: valutalo leggendolo.")

    return CommandReview(
        categories=categories,
        labels=[_CATEGORY_LABELS[category] for category in categories],
        paths=_collect_paths(text),
        warnings=warnings,
        parsed=parsed,
    )
