from __future__ import annotations

import io
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import tarfile
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml  # type: ignore[import-untyped]

# Regola dello standard Agent Skills (agentskills.io) per il campo `name`:
# 1-64 caratteri, minuscole a-z e 0-9, trattini singoli, senza inizio/fine trattino.
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_NAME = 64
_MAX_DESCRIPTION = 1024
_MAX_COMPATIBILITY = 500

# Limiti difensivi per import da fonti esterne (archivi/repo/registry).
_MAX_ARCHIVE_FILES = 2_000
_MAX_TOTAL_BYTES = 50 * 1024 * 1024  # dimensione decompressa massima (anti size-bomb)
_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
_DOWNLOAD_TIMEOUT = 30
_GIT_TIMEOUT = 90
_MAX_REDIRECTS = 5


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Separa il frontmatter YAML dal corpo Markdown di un SKILL.md."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        front = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        front = {}
    if not isinstance(front, dict):
        front = {}
    return front, parts[2].lstrip("\n")


def validate_skill(name: Any, dir_name: str, front: dict[str, Any]) -> list[str]:
    """Valida un SKILL.md contro lo standard Agent Skills. Ritorna la lista di errori."""
    errors: list[str] = []
    if not isinstance(name, str) or not name:
        errors.append("`name` mancante nel frontmatter.")
    else:
        if len(name) > _MAX_NAME:
            errors.append(f"`name` oltre {_MAX_NAME} caratteri.")
        if not _NAME_RE.match(name):
            errors.append(
                "`name` non valido: solo minuscole a-z, cifre e trattini singoli, "
                "senza trattino iniziale/finale o doppio."
            )
        if name != dir_name:
            errors.append(f"`name` ('{name}') deve coincidere con la cartella ('{dir_name}').")
    description = front.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("`description` mancante o vuota.")
    elif len(description) > _MAX_DESCRIPTION:
        errors.append(f"`description` oltre {_MAX_DESCRIPTION} caratteri.")
    compatibility = front.get("compatibility")
    if isinstance(compatibility, str) and len(compatibility) > _MAX_COMPATIBILITY:
        errors.append(f"`compatibility` oltre {_MAX_COMPATIBILITY} caratteri.")
    return errors


def _skill_info(directory: Path) -> dict[str, Any]:
    skill_md = directory / "SKILL.md"
    front, body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    errors = validate_skill(front.get("name"), directory.name, front)
    metadata = front.get("metadata")
    return {
        "name": directory.name,
        "declared_name": front.get("name"),
        "description": front.get("description") or "",
        "license": front.get("license"),
        "compatibility": front.get("compatibility"),
        "allowed_tools": front.get("allowed-tools") or front.get("allowed_tools"),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "has_scripts": (directory / "scripts").is_dir(),
        "has_references": (directory / "references").is_dir(),
        "has_assets": (directory / "assets").is_dir(),
        "resource_count": sum(
            1 for path in directory.rglob("*") if path.is_file() and path.name != "SKILL.md"
        ),
        "body_lines": len(body.splitlines()),
        "valid": not errors,
        "errors": errors,
    }


def list_skills(skills_dir: Path) -> list[dict[str, Any]]:
    if not skills_dir.exists():
        return []
    result: list[dict[str, Any]] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            result.append(_skill_info(skill_md.parent))
        except OSError:
            continue
    return result


def confine_to_directory(base_dir: Path, relative_name: str) -> Path:
    """Risolve relative_name come figlio diretto di base_dir; ValueError se esce dalla directory."""
    base = base_dir.resolve()
    candidate = (base / relative_name).resolve()
    if candidate.parent != base:
        raise ValueError("Percorso non valido.")
    return candidate


def _skill_dir(skills_dir: Path, name: str) -> Path:
    """Cartella della skill, confinata in skills_dir (difesa oltre alla regex del name)."""
    if not _NAME_RE.match(name) or len(name) > _MAX_NAME:
        raise ValueError("Nome skill non valido.")
    return confine_to_directory(skills_dir, name)


def read_skill(skills_dir: Path, name: str) -> dict[str, Any]:
    directory = _skill_dir(skills_dir, name)
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(name)
    info = _skill_info(directory)
    info["content"] = skill_md.read_text(encoding="utf-8")
    return info


def build_skill_md(name: str, description: str, body: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body.strip()}\n"


def write_skill(skills_dir: Path, name: str, content: str) -> dict[str, Any]:
    """Scrive/aggiorna un SKILL.md dopo validazione contro lo standard."""
    directory = _skill_dir(skills_dir, name)
    front, _ = parse_frontmatter(content)
    errors = validate_skill(front.get("name", name), name, front)
    if errors:
        raise ValueError("; ".join(errors))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(content, encoding="utf-8")
    return read_skill(skills_dir, name)


def delete_skill(skills_dir: Path, name: str) -> None:
    directory = _skill_dir(skills_dir, name)
    if not directory.is_dir():
        raise FileNotFoundError(name)
    shutil.rmtree(directory)


# ---------------------------------------------------------------------------
# File di risorsa: skill multi-file (scripts/ references/ assets/ ...)
# ---------------------------------------------------------------------------


def _resolve_within(base: Path, relpath: str) -> Path:
    """Risolve relpath (anche annidato) dentro base; ValueError se ne esce o è symlink.

    Segue la regola §8 delle secure-coding-guidelines: `resolve()` *poi*
    `is_relative_to(root)` per battere sia il traversal `../` sia le fughe via symlink.
    """
    if not relpath or "\x00" in relpath:
        raise ValueError("Percorso file non valido.")
    base = base.resolve()
    candidate = (base / relpath).resolve()
    if candidate == base or not candidate.is_relative_to(base):
        raise ValueError("Percorso file non valido.")
    return candidate


def list_skill_files(skills_dir: Path, name: str) -> list[dict[str, Any]]:
    """Elenca tutti i file di una skill (relpath POSIX, size, is_dir). Salta i symlink."""
    directory = _skill_dir(skills_dir, name)
    if not directory.is_dir():
        raise FileNotFoundError(name)
    resolved = directory.resolve()
    result: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            continue
        is_dir = path.is_dir()
        result.append(
            {
                "path": path.relative_to(resolved).as_posix(),
                "is_dir": is_dir,
                "size": path.stat().st_size if path.is_file() else 0,
            }
        )
    return result


def read_skill_file(skills_dir: Path, name: str, relpath: str) -> dict[str, Any]:
    directory = _skill_dir(skills_dir, name)
    target = _resolve_within(directory, relpath)
    if not target.is_file():
        raise FileNotFoundError(relpath)
    data = target.read_bytes()
    try:
        return {"path": relpath, "content": data.decode("utf-8"), "binary": False}
    except UnicodeDecodeError:
        return {"path": relpath, "content": "", "binary": True, "size": len(data)}


def write_skill_file(
    skills_dir: Path, name: str, relpath: str, content: str | bytes
) -> dict[str, Any]:
    """Scrive/crea un file di risorsa dentro la cartella skill (crea sottocartelle mancanti).

    Se il file è il `SKILL.md` di primo livello, il frontmatter viene validato prima di scrivere.
    """
    directory = _skill_dir(skills_dir, name)
    directory.mkdir(parents=True, exist_ok=True)
    target = _resolve_within(directory, relpath)
    if target == (directory.resolve() / "SKILL.md") and isinstance(content, str):
        front, _ = parse_frontmatter(content)
        errors = validate_skill(front.get("name", name), name, front)
        if errors:
            raise ValueError("; ".join(errors))
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return read_skill_file(skills_dir, name, relpath)


def delete_skill_file(skills_dir: Path, name: str, relpath: str) -> None:
    directory = _skill_dir(skills_dir, name)
    target = _resolve_within(directory, relpath)
    if target == (directory.resolve() / "SKILL.md"):
        raise ValueError("SKILL.md non è eliminabile come file di risorsa.")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    else:
        raise FileNotFoundError(relpath)


# ---------------------------------------------------------------------------
# Audit installazioni (log append-only + revoca)
# ---------------------------------------------------------------------------


def _installs_log(skills_dir: Path) -> Path:
    return skills_dir.parent / "state" / "skill_installs.jsonl"


def record_skill_event(
    skills_dir: Path,
    *,
    name: str,
    source: str,
    value: str,
    by: str,
    action: str,
) -> None:
    path = _installs_log(skills_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "name": name,
        "source": source,
        "value": value,
        "by": by,
        "action": action,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def list_skill_installs(skills_dir: Path) -> list[dict[str, Any]]:
    path = _installs_log(skills_dir)
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


# ---------------------------------------------------------------------------
# Installazione da fonti esterne: archivio, git, registry
# ---------------------------------------------------------------------------


def _guard_external_host(url: str) -> None:
    """Guardia SSRF (§2): schema http/https e IP risolto non link-local/metadata.

    Non blocca loopback/RFC1918: questo è un harness locale in cui l'operatore incolla
    URL espliciti (anche `localhost` per i test), mentre il bersaglio vero — i metadati
    cloud su 169.254.169.254 (coperto da link-local) — resta chiuso.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Schema URL non permesso: usa http/https.")
    host = parsed.hostname
    if not host:
        raise ValueError("URL senza host.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise ValueError(f"Host non risolvibile: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError(f"Host non permesso (link-local/metadata): {ip}")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Ri-applica la guardia SSRF a ogni hop di redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        _guard_external_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_bytes(url: str, max_bytes: int = _MAX_DOWNLOAD_BYTES) -> bytes:
    _guard_external_host(url)
    opener = urllib.request.build_opener(_GuardedRedirectHandler())
    request = urllib.request.Request(url, headers={"User-Agent": "agent-harness-skills/1"})
    with opener.open(request, timeout=_DOWNLOAD_TIMEOUT) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Download oltre il limite di {max_bytes} byte.")
    return data


def _sniff_archive_fmt(data: bytes, url: str = "") -> str:
    if data[:4] == b"PK\x03\x04":
        return "zip"
    if data[:2] == b"\x1f\x8b":
        return "tar.gz"
    lowered = url.lower()
    if lowered.endswith(".zip"):
        return "zip"
    if lowered.endswith((".tar.gz", ".tgz", ".tar")):
        return "tar.gz"
    raise ValueError("Formato archivio non riconosciuto (attesi .zip o .tar.gz).")


def _extract_archive(data: bytes, fmt: str, dest: Path) -> None:
    """Estrazione blindata (§8/§10): no path assoluti/`..`/symlink/hardlink; cap file/byte."""
    total = 0
    count = 0
    if fmt == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError("Symlink non permessi nell'archivio.")
                count += 1
                total += info.file_size
                if count > _MAX_ARCHIVE_FILES or total > _MAX_TOTAL_BYTES:
                    raise ValueError("Archivio troppo grande (troppi file o byte).")
                target = _resolve_within(dest, info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for member in archive:
                if member.isdir():
                    continue
                if member.issym() or member.islnk() or not member.isfile():
                    raise ValueError("Voce archivio non permessa (symlink/hardlink/speciale).")
                count += 1
                total += member.size
                if count > _MAX_ARCHIVE_FILES or total > _MAX_TOTAL_BYTES:
                    raise ValueError("Archivio troppo grande (troppi file o byte).")
                target = _resolve_within(dest, member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                with extracted as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)


def _find_skill_root(root: Path) -> Path:
    """Individua la cartella con SKILL.md; sceglie la più superficiale se ce n'è più d'una."""
    matches = [md.parent for md in root.rglob("SKILL.md") if md.is_file()]
    if not matches:
        raise ValueError("Nessun SKILL.md trovato nell'archivio/repo.")
    matches.sort(key=lambda path: len(path.parts))
    return matches[0]


def _finalize_install(
    skills_dir: Path,
    source_tree: Path,
    *,
    source: str,
    value: str,
    by: str,
    force: bool,
) -> dict[str, Any]:
    skill_src = _find_skill_root(source_tree)
    front, _ = parse_frontmatter((skill_src / "SKILL.md").read_text(encoding="utf-8"))
    name = front.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name) or len(name) > _MAX_NAME:
        raise ValueError("`name` mancante o non valido nel frontmatter della skill.")
    errors = validate_skill(name, name, front)
    if errors:
        raise ValueError("; ".join(errors))
    target = _skill_dir(skills_dir, name)
    if target.exists() and not force:
        raise FileExistsError(name)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # symlinks=False: eventuali symlink residui vengono copiati come file reali, non seguiti fuori.
    shutil.copytree(skill_src, target, symlinks=False)
    record_skill_event(skills_dir, name=name, source=source, value=value, by=by, action="install")
    return read_skill(skills_dir, name)


def install_skill_from_archive(
    skills_dir: Path,
    data: bytes,
    fmt: str | None = None,
    *,
    source: str = "archive",
    value: str = "",
    by: str = "human",
    force: bool = False,
) -> dict[str, Any]:
    resolved_fmt = fmt or _sniff_archive_fmt(data, value)
    with TemporaryDirectory() as tmp:
        dest = Path(tmp) / "extract"
        dest.mkdir()
        _extract_archive(data, resolved_fmt, dest)
        return _finalize_install(skills_dir, dest, source=source, value=value, by=by, force=force)


def install_skill_from_url(
    skills_dir: Path,
    url: str,
    *,
    by: str = "human",
    force: bool = False,
) -> dict[str, Any]:
    data = _download_bytes(url)
    return install_skill_from_archive(
        skills_dir,
        data,
        _sniff_archive_fmt(data, url),
        source="archive_url",
        value=url,
        by=by,
        force=force,
    )


def install_skill_from_git(
    skills_dir: Path,
    repo_url: str,
    *,
    ref: str | None = None,
    subdir: str | None = None,
    by: str = "human",
    force: bool = False,
) -> dict[str, Any]:
    _guard_external_host(repo_url)  # http/https + no link-local; niente file://, git://, ssh
    env = {
        "PATH": os.environ.get("PATH", ""),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "GIT_ALLOW_PROTOCOL": "http:https",
    }
    with TemporaryDirectory() as tmp:
        clone = Path(tmp) / "repo"
        command = ["git", "clone", "--depth", "1", "--no-recurse-submodules"]
        if ref:
            command += ["--branch", ref]
        command += ["--", repo_url, str(clone)]  # list-form, mai shell (§9)
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=_GIT_TIMEOUT, check=False, env=env
        )
        if result.returncode != 0:
            raise ValueError(f"git clone fallito: {(result.stderr or '').strip()[:300]}")
        shutil.rmtree(clone / ".git", ignore_errors=True)
        source_tree = _resolve_within(clone, subdir) if subdir else clone
        return _finalize_install(
            skills_dir, source_tree, source="git", value=repo_url, by=by, force=force
        )


def registry_archive_url(registry_url: str, name: str) -> str:
    """Adattatore (thin) verso il registry agentskills.io: base + nome → URL archivio.

    Isolato apposta: se la forma reale dell'API differisce, si cambia solo qui.
    """
    if not _NAME_RE.match(name) or len(name) > _MAX_NAME:
        raise ValueError("Nome skill non valido.")
    return f"{registry_url.rstrip('/')}/{name}.zip"


def install_skill_from_registry(
    skills_dir: Path,
    name: str,
    *,
    registry_url: str,
    by: str = "human",
    force: bool = False,
) -> dict[str, Any]:
    url = registry_archive_url(registry_url, name)
    data = _download_bytes(url)
    return install_skill_from_archive(
        skills_dir,
        data,
        _sniff_archive_fmt(data, url),
        source="registry",
        value=name,
        by=by,
        force=force,
    )


def install_skill(
    skills_dir: Path,
    source: str,
    value: str,
    *,
    ref: str | None = None,
    subdir: str | None = None,
    registry_url: str = "",
    by: str = "human",
    force: bool = False,
) -> dict[str, Any]:
    """Dispatch unico usato da API REST e tool MCP."""
    if source == "archive_url":
        return install_skill_from_url(skills_dir, value, by=by, force=force)
    if source == "git":
        return install_skill_from_git(
            skills_dir, value, ref=ref, subdir=subdir, by=by, force=force
        )
    if source == "registry":
        if not registry_url:
            raise ValueError("Registry non configurato.")
        return install_skill_from_registry(
            skills_dir, value, registry_url=registry_url, by=by, force=force
        )
    raise ValueError(f"Sorgente install non supportata: {source}")
