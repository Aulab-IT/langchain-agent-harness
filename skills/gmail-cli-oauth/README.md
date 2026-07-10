# Gmail CLI OAuth Skill

Skill e CLI Python per collegare Gmail usando OAuth 2.0 ufficiale e Gmail API.

## File

- `SKILL.md`: istruzioni operative della skill.
- `gmail_oauth_cli.py`: CLI per autorizzare, verificare profilo e listare label Gmail.
- `requirements.txt`: dipendenze Python.

## Installazione

```bash
cd /skills/gmail-cli-oauth
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Configurazione Google Cloud

1. Crea/seleziona un progetto Google Cloud.
2. Abilita Gmail API.
3. Configura OAuth consent screen.
4. Crea OAuth client di tipo Desktop app.
5. Scarica il JSON OAuth come `credentials.json` sul tuo computer.

## Uso

Autorizza Gmail con scope readonly:

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

## Sicurezza

Non incollare password, codici 2FA, cookie, `credentials.json` o `token.json` in chat. Il consenso va completato nel browser ufficiale Google; la CLI non stampa token. Evita di salvare token e credenziali in repository Git, cartelle condivise o directory sincronizzate.
