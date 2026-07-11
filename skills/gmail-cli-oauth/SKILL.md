---
name: gmail-cli-oauth
description: Usa una CLI Python per connettere Gmail tramite OAuth 2.0 ufficiale, verificare il profilo Gmail e listare label senza ricevere password o codici dall'utente.
---

# Skill: Gmail CLI OAuth

Usa questa skill quando l'utente chiede di collegare Gmail da terminale/CLI o di preparare una connessione Gmail OAuth sicura.

## Regole di sicurezza

- Non chiedere mai password Gmail, codici 2FA, cookie, sessioni browser, access token o refresh token.
- Non chiedere mai di incollare `credentials.json` o `token.json`; chiedi solo path locali.
- L'utente deve autorizzare l'app nel browser Google ufficiale tramite OAuth.
- Usa lo scope minimo necessario; default: `https://www.googleapis.com/auth/gmail.readonly`.
- Non stampare token. Riporta solo output non segreto, come email account, conteggi o nomi label se l'utente li vuole.
- Salva token solo su macchina dell'utente, ad esempio `~/.config/gmail-cli-oauth/token.json`, evitando repository Git, cartelle condivise o directory sincronizzate.

## Fonti ufficiali

- OAuth desktop/installed apps: https://developers.google.com/identity/protocols/oauth2/native-app
- Gmail API scopes: https://developers.google.com/workspace/gmail/api/auth/scopes
- Gmail API Python quickstart: https://developers.google.com/workspace/gmail/api/quickstart/python
- Loopback redirect flow: https://developers.google.com/identity/protocols/oauth2/resources/loopback-migration

## Prerequisiti Google Cloud

1. Crea/seleziona un progetto Google Cloud.
2. Abilita Gmail API.
3. Configura OAuth consent screen.
4. Crea un OAuth client di tipo **Desktop app**.
5. Scarica il JSON OAuth come `credentials.json` sul computer dell'utente.

## Scope consigliati

| Azione | Scope minimo |
|---|---|
| Profilo, label, lettura messaggi | `readonly` = `https://www.googleapis.com/auth/gmail.readonly` |
| Solo metadati | `metadata` = `https://www.googleapis.com/auth/gmail.metadata` |
| Invio email | `send` = `https://www.googleapis.com/auth/gmail.send` |
| Lettura e modifica | `modify` = `https://www.googleapis.com/auth/gmail.modify` |
| Accesso completo | `full` = `https://mail.google.com/` solo se indispensabile |

## Installazione dipendenze CLI

```bash
python -m venv .venv
. .venv/bin/activate
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

## Uso CLI

Autorizzazione:

```bash
python gmail_oauth_cli.py auth --credentials /path/credentials.json --scope readonly
```

Verifica connessione:

```bash
python gmail_oauth_cli.py profile --credentials /path/credentials.json
```

Lista label:

```bash
python gmail_oauth_cli.py labels --credentials /path/credentials.json
```

Elimina token locale:

```bash
python gmail_oauth_cli.py revoke-local
```

## CLI minima autosufficiente

Se il file `gmail_oauth_cli.py` non è già presente come risorsa della skill, crealo con questo contenuto:

```python
#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os
from pathlib import Path
from typing import Sequence

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    Request = Credentials = InstalledAppFlow = build = None

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
    scopes = []
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
        raise SystemExit("Dipendenze Google mancanti. Installa con: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")

def load_credentials(token_path: Path, scopes: Sequence[str]):
    require_google_libraries()
    if not token_path.exists():
        return None
    return Credentials.from_authorized_user_file(str(token_path), list(scopes))

def save_credentials(token_path: Path, creds) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass

def get_authorized_credentials(credentials_path: Path, token_path: Path, scopes: Sequence[str], *, do_auth: bool):
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
        raise SystemExit("Token mancante o non valido. Esegui prima: gmail_oauth_cli.py auth --credentials /path/credentials.json")
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), list(scopes))
    creds = flow.run_local_server(port=0, open_browser=True)
    save_credentials(token_path, creds)
    return creds

def gmail_service(creds):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)

def cmd_auth(args):
    scopes = resolve_scopes(args.scope)
    token_path = expand_path(args.token)
    creds = get_authorized_credentials(expand_path(args.credentials), token_path, scopes, do_auth=True)
    safe = {"status": "authorized", "tokenSavedTo": str(token_path), "scopes": scopes, "verification": "token_saved"}
    profile_scopes = {SCOPE_ALIASES["readonly"], SCOPE_ALIASES["metadata"], SCOPE_ALIASES["modify"], SCOPE_ALIASES["full"]}
    if any(scope in profile_scopes for scope in scopes):
        profile = gmail_service(creds).users().getProfile(userId="me").execute()
        safe.update({"verification": "gmail_profile_ok", "emailAddress": profile.get("emailAddress"), "messagesTotal": profile.get("messagesTotal"), "threadsTotal": profile.get("threadsTotal")})
    print(json.dumps(safe, indent=2, ensure_ascii=False))

def cmd_profile(args):
    scopes = resolve_scopes(args.scope)
    creds = get_authorized_credentials(expand_path(args.credentials), expand_path(args.token), scopes, do_auth=False)
    print(json.dumps(gmail_service(creds).users().getProfile(userId="me").execute(), indent=2, ensure_ascii=False))

def cmd_labels(args):
    scopes = resolve_scopes(args.scope)
    creds = get_authorized_credentials(expand_path(args.credentials), expand_path(args.token), scopes, do_auth=False)
    result = gmail_service(creds).users().labels().list(userId="me").execute()
    print(json.dumps({"labels": result.get("labels", [])}, indent=2, ensure_ascii=False))

def cmd_revoke_local(args):
    token_path = expand_path(args.token)
    if token_path.exists():
        token_path.unlink()
        print(json.dumps({"status": "deleted", "tokenPath": str(token_path)}, indent=2))
    else:
        print(json.dumps({"status": "not_found", "tokenPath": str(token_path)}, indent=2))

def build_parser():
    parser = argparse.ArgumentParser(description="Connetti Gmail tramite OAuth 2.0 da CLI senza gestire password o codici in chat.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    def add_common(sub):
        sub.add_argument("--credentials", required=True, help="Path al credentials.json OAuth scaricato da Google Cloud.")
        sub.add_argument("--token", default=DEFAULT_TOKEN_PATH, help=f"Path token locale. Default: {DEFAULT_TOKEN_PATH}")
        sub.add_argument("--scope", action="append", default=None, help="Scope alias: readonly, metadata, send, modify, full; oppure URL scope completo. Ripetibile. Default: readonly.")
    auth = subparsers.add_parser("auth", help="Avvia OAuth nel browser, salva token locale e verifica il profilo Gmail."); add_common(auth); auth.set_defaults(func=cmd_auth)
    profile = subparsers.add_parser("profile", help="Mostra il profilo Gmail autorizzato."); add_common(profile); profile.set_defaults(func=cmd_profile)
    labels = subparsers.add_parser("labels", help="Lista label Gmail."); add_common(labels); labels.set_defaults(func=cmd_labels)
    revoke = subparsers.add_parser("revoke-local", help="Elimina il token locale."); revoke.add_argument("--token", default=DEFAULT_TOKEN_PATH); revoke.set_defaults(func=cmd_revoke_local)
    return parser

def main():
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
```

## Risoluzione problemi

- `redirect_uri_mismatch`: usa credenziali di tipo Desktop app, oppure configura esattamente il redirect URI locale per una Web app.
- `access_denied`: consenso negato o app non autorizzata.
- `invalid_scope`: scope scritto male o non consentito.
- App non verificata: per test personali aggiungi l'account come test user; per uso pubblico può servire verifica Google.
- Token scaduto: la CLI prova il refresh; se fallisce, riesegui `auth`.
