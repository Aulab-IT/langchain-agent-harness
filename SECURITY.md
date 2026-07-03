# Modello di sicurezza

## Dati considerati non attendibili

- obiettivi e testo inseriti dall'utente;
- comandi proposti dal modello;
- contenuti di pagine e risultati di ricerca;
- file presenti nel workspace;
- output restituiti da tool e server MCP.

Questi dati non possono modificare prompt di sistema, permessi o policy del runtime.

## Segreti

`OPENAI_API_KEY` e `LANGSMITH_API_KEY` vengono letti dall'ambiente. Non sono montati nel
container Docker, non vengono inclusi nei log e `.env` è ignorato da Git.

## Esecuzione

Il container:

- non possiede rete;
- vede soltanto `workspace`;
- usa un utente non root;
- non riceve socket Docker né variabili dell'host;
- ha limiti di CPU, RAM, PID e tempo;
- richiede approvazione umana.

## Accesso web

`browser_read` accetta soltanto HTTP/HTTPS, rifiuta credenziali nell'URL, risolve
l'hostname e blocca indirizzi privati, loopback, link-local e riservati. Ogni redirect
viene rivalidato. Tipo e dimensione della risposta sono limitati.

Questa protezione riduce il rischio SSRF ma non sostituisce un proxy egress con policy di
rete in un deployment ostile.

## Audit

`state/audit.jsonl` contiene soltanto timestamp, nome tool, stato e durata. Argomenti e
output vengono deliberatamente esclusi perché possono contenere dati sensibili.

## Limiti del progetto

Il repository è didattico, non un servizio multi-tenant. Prima di un deployment reale
servono almeno isolamento per utente, autenticazione, rate limiting, gestione centralizzata
dei segreti, proxy egress, scanning dipendenze e retention policy.

