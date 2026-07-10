#!/usr/bin/env python3
"""CLI sicura per connettere Gmail tramite OAuth 2.0.

Non stampa token e non richiede password/codici all'utente. L'autorizzazione
avviene nel browser tramite il flusso OAuth ufficiale di Google.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:  # Permette --help senza dipendenze installate.
    Request = None
    Credentials = None
    InstalledAppFlow = None
    build = None

SCOPE_ALIASES = {
    "readonly": "https://www.googleapis.com/auth/gmail.readonly",
    "metadata": "https://www.googleapis.com/auth/gmail.metadata",
    "send": "https://www.googleapis.com/auth/gmail.send",
    "modify": "https://www.googleapis.com/auth/gmail.modify",
    "full": "https://mail.google.com/",
}

DEFAULT_TOKEN_PATH = "~/.config/gmail-cli-oauth/token.json"


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def resolve_scopes(scope_names: Sequence[str] | None) -> list[str]:
    if not scope_names:
        scope_names = ["readonly"]
    scopes: list[str] = []
    for name in scope_names:
        if name in SCOPE_ALIASES:
            scopes.append(SCOPE_ALIASES[name])
        elif name.startswith("https://"):
            scopes.append(name)
        else:
            valid = ", ".join(sorted(SCOPE_ALIASES))
            raise SystemExit(f"Scope non valido: {name}. Valori validi: {valid}, oppure URL scope completo.")
    return scopes


def require_google_libraries() -> None:
    if any(item is None for item in (Request, Credentials, InstalledAppFlow, build)):
        raise SystemExit(
            "Dipendenze Google mancanti. Installa con: "
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )


def load_credentials(token_path: Path, scopes: Sequence[str]):
    require_google_libraries()
    if not token_path.exists():
        return None
    return Credentials.from_authorized_user_file(str(token_path), list(scopes))


def save_credentials(token_path: Path, creds: Credentials) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        # Su alcuni filesystem/OS chmod può non essere supportato.
        pass


def get_authorized_credentials(credentials_path: Path, token_path: Path, scopes: Sequence[str], *, do_auth: bool) -> Credentials:
    if not credentials_path.exists():
        raise SystemExit(f"File credentials non trovato: {credentials_path}")

    creds = load_credentials(token_path, scopes)
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(token_path, creds)
        return creds

    if not do_auth:
        raise SystemExit(
            "Token mancante o non valido. Esegui prima: gmail_oauth_cli.py auth "
            "--credentials /path/credentials.json"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), list(scopes))
    creds = flow.run_local_server(port=0, open_browser=True)
    save_credentials(token_path, creds)
    return creds


def gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def cmd_auth(args: argparse.Namespace) -> None:
    scopes = resolve_scopes(args.scope)
    credentials_path = expand_path(args.credentials)
    token_path = expand_path(args.token)
    creds = get_authorized_credentials(credentials_path, token_path, scopes, do_auth=True)
    safe = {
        "status": "authorized",
        "tokenSavedTo": str(token_path),
        "scopes": scopes,
        "verification": "token_saved",
    }
    # Verifica minima non distruttiva solo con scope che consentono lettura profilo.
    profile_compatible_scopes = {
        SCOPE_ALIASES["readonly"],
        SCOPE_ALIASES["metadata"],
        SCOPE_ALIASES["modify"],
        SCOPE_ALIASES["full"],
    }
    if any(scope in profile_compatible_scopes for scope in scopes):
        service = gmail_service(creds)
        profile = service.users().getProfile(userId="me").execute()
        safe.update(
            {
                "verification": "gmail_profile_ok",
                "emailAddress": profile.get("emailAddress"),
                "messagesTotal": profile.get("messagesTotal"),
                "threadsTotal": profile.get("threadsTotal"),
            }
        )
    print(json.dumps(safe, indent=2, ensure_ascii=False))


def cmd_profile(args: argparse.Namespace) -> None:
    scopes = resolve_scopes(args.scope)
    creds = get_authorized_credentials(expand_path(args.credentials), expand_path(args.token), scopes, do_auth=False)
    profile = gmail_service(creds).users().getProfile(userId="me").execute()
    print(json.dumps(profile, indent=2, ensure_ascii=False))


def cmd_labels(args: argparse.Namespace) -> None:
    scopes = resolve_scopes(args.scope)
    creds = get_authorized_credentials(expand_path(args.credentials), expand_path(args.token), scopes, do_auth=False)
    result = gmail_service(creds).users().labels().list(userId="me").execute()
    labels = result.get("labels", [])
    print(json.dumps({"labels": labels}, indent=2, ensure_ascii=False))


def cmd_revoke_local(args: argparse.Namespace) -> None:
    token_path = expand_path(args.token)
    if token_path.exists():
        token_path.unlink()
        print(json.dumps({"status": "deleted", "tokenPath": str(token_path)}, indent=2))
    else:
        print(json.dumps({"status": "not_found", "tokenPath": str(token_path)}, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Connetti Gmail tramite OAuth 2.0 da CLI senza gestire password o codici in chat."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub):
        sub.add_argument("--credentials", required=True, help="Path al credentials.json OAuth scaricato da Google Cloud.")
        sub.add_argument("--token", default=DEFAULT_TOKEN_PATH, help=f"Path token locale. Default: {DEFAULT_TOKEN_PATH}")
        sub.add_argument(
            "--scope",
            action="append",
            default=None,
            help="Scope alias: readonly, metadata, send, modify, full; oppure URL scope completo. Ripetibile. Default: readonly.",
        )

    auth = subparsers.add_parser("auth", help="Avvia OAuth nel browser, salva token locale e verifica il profilo Gmail.")
    add_common(auth)
    auth.set_defaults(func=cmd_auth)

    profile = subparsers.add_parser("profile", help="Mostra il profilo Gmail dell'utente autorizzato.")
    add_common(profile)
    profile.set_defaults(func=cmd_profile)

    labels = subparsers.add_parser("labels", help="Lista label Gmail come test non distruttivo.")
    add_common(labels)
    labels.set_defaults(func=cmd_labels)

    revoke = subparsers.add_parser("revoke-local", help="Elimina il token locale senza revocare l'accesso lato Google.")
    revoke.add_argument("--token", default=DEFAULT_TOKEN_PATH, help=f"Path token locale. Default: {DEFAULT_TOKEN_PATH}")
    revoke.set_defaults(func=cmd_revoke_local)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
