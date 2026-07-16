"""Applica un contratto didattico uniforme ai dodici notebook del percorso."""

# ruff: noqa: E501, RUF001

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import nbformat

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ROOT / "notebooks"
GENERATED_TAGS = {"didactic-comment", "didactic-example"}


@dataclass(frozen=True)
class BlockNote:
    title: str
    explanation: str
    expected: str


@dataclass(frozen=True)
class ExtraExample:
    title: str
    explanation: str
    source: str
    expected: str


def note(title: str, explanation: str, expected: str) -> BlockNote:
    return BlockNote(title, dedent(explanation).strip(), dedent(expected).strip())


def extra(title: str, explanation: str, source: str, expected: str) -> ExtraExample:
    return ExtraExample(
        title,
        dedent(explanation).strip(),
        dedent(source).strip(),
        dedent(expected).strip(),
    )


BLOCK_NOTES: dict[str, list[BlockNote]] = {
    "01": [
        note("Caricamento della configurazione", "Il blocco cerca `.env` risalendo dalla directory corrente. In questo modo il notebook funziona sia dalla radice sia da `notebooks/`, senza importare configurazione dal progetto.", "Una riga simile a `Ambiente caricato da: .../.env`. Se il file o la chiave mancano, compare un errore esplicito prima di qualsiasi chiamata API."),
        note("Creazione del modello", "`ChatOpenAI` adatta il provider all'interfaccia LangChain. `store=False` evita la conservazione server-side e il nome modello resta configurabile tramite ambiente.", "`Modello pronto: <nome-modello>`. Non viene ancora effettuata alcuna chiamata al modello."),
        note("Costruzione dei messaggi", "Qui si separano istruzioni stabili (`SystemMessage`) e richiesta dell'utente (`HumanMessage`). Il blocco prepara dati, ma non invoca ancora il provider.", "Nessun testo stampato. La variabile `messaggi` contiene esattamente due oggetti tipizzati."),
        note("Prima invocazione", "`invoke` esegue una singola inferenza. La risposta è un `AIMessage`, non una semplice stringa: `.text` ne estrae la parte leggibile.", "Una frase in italiano che distingue modello e agente. La formulazione varia tra esecuzioni, mentre il significato dovrebbe restare equivalente."),
        note("Ispezione dei metadati", "Il risultato conserva tipo e usage. Questo dato permette al runtime di misurare costo e budget senza stimare tutto dal testo.", "`Tipo: AIMessage` seguito da un dizionario con token di input, output e totale. I numeri dipendono dal modello."),
        note("Prompt parametrico", "`ChatPromptTemplate` trasforma un modello di messaggi in un componente riutilizzabile. `{argomento}` viene sostituito solo al momento dell'invocazione.", "Nessun output. `prompt` contiene due template di messaggio e richiede la variabile `argomento`."),
        note("Composizione LCEL", "L'operatore `|` compone prompt, modello e parser. Il risultato è una pipeline invocabile: l'output del componente precedente diventa input del successivo.", "Nessun output. `chain` è pronta e restituirà direttamente una stringa anziché un `AIMessage`."),
        note("Esecuzione della chain", "Il dizionario riempie il parametro del prompt. La stessa chain può essere riusata con argomenti diversi senza duplicare istruzioni.", "Una spiegazione semplice della list comprehension con un piccolo esempio Python. Testo e codice possono variare."),
        note("Definizione di un tool", "Il decoratore converte la funzione in uno strumento. Tipi e docstring diventano schema che il modello usa per decidere quando e come chiamarlo; la validazione positiva impedisce misure senza senso.", "Nessun output. `area_rettangolo` espone gli argomenti numerici `base` e `altezza`."),
        note("Creazione del loop agente", "`create_agent` collega modello e tool. Il system prompt impone di usare il calcolo verificabile invece di produrre un numero soltanto per generazione linguistica.", "Nessun output. `agente` è un graph invocabile con stato `messages`."),
        note("Richiesta che richiede un tool", "La domanda contiene valori compatibili con lo schema. Il modello dovrebbe emettere una tool call, ricevere `100.0` e solo dopo formulare la risposta finale.", "Una risposta che indica area pari a `100 m²`. La frase varia, ma il valore deve provenire dal tool."),
        note("Trace del ciclo ReAct", "La lista finale dei messaggi espone il ciclo completo: input umano, richiesta del modello, osservazione del tool e risposta conclusiva. È il modo più semplice per non trattare l'agente come scatola nera.", "Quattro passaggi circa: `HumanMessage`, `AIMessage` con `area_rettangolo`, `ToolMessage` con `100.0`, quindi `AIMessage` finale."),
    ],
    "02": [
        note("Caricamento della configurazione", "Il setup è locale al notebook e non dipende da moduli del repository. La ricerca ascendente rende stabile il percorso di `.env`.", "Percorso del file `.env`, oppure errore immediato se configurazione assente."),
        note("Inizializzazione del modello", "Viene creato un solo client e riusato nelle sezioni successive, evitando configurazioni divergenti tra esempi.", "`Modello pronto: <nome-modello>`."),
        note("Tool puro e test diretto", "Prima di coinvolgere un agente si verifica il tool isolatamente. Questo separa errori della funzione da errori di scelta del modello.", "Il numero `3`, perché la frase contiene tre parole."),
        note("Creazione del workspace confinato", "Il path viene normalizzato con `resolve()` e poi confrontato con la root. Controllare la stringa prima della normalizzazione non basterebbe contro sequenze `..`.", "Un percorso temporaneo con prefisso `nb_workspace_`. Nessun file viene ancora creato."),
        note("Test negativo del path traversal", "Il caso malevolo viene provato intenzionalmente. Una difesa è utile solo se il percorso vietato produce un errore osservabile.", "`Bloccato correttamente: Percorso fuori dal workspace: ../fuori.txt`."),
        note("Tool di lettura e scrittura", "Entrambi passano dalla stessa funzione di confinement. Centralizzare la guardia evita che un tool dimentichi il controllo.", "Nessun output. Sono disponibili `scrivi_file` e `leggi_file`."),
        note("Esecuzione con timeout", "Il sottoprocesso riceve argomenti come lista e non usa shell. Exit code, stdout e stderr restano distinti, così l'agente può verificare davvero il risultato.", "Nessun output. `esegui_python` è definito; un timeout restituirà un messaggio controllato."),
        note("Assemblaggio dell'agente operativo", "Il modello vede quattro strumenti con responsabilità diverse. Il prompt richiede una verifica dopo la scrittura del codice.", "Nessun output. L'agente è pronto a leggere, scrivere ed eseguire Python."),
        note("Flusso write–execute–verify", "La richiesta non può essere soddisfatta correttamente con solo testo: deve produrre un file, eseguirlo e interpretare l'exit code.", "Una risposta che conferma risultato `55`. Nel workspace deve comparire `somma.py`; trace e formulazione dipendono dal modello."),
    ],
    "03": [
        note("Setup isolato", "La configurazione viene caricata senza importare il package finale, mantenendo il notebook autonomo.", "Percorso `.env` utilizzato."),
        note("Client del modello", "Lo stesso modello verrà usato prima senza memoria e poi dentro un graph con checkpointer, così il confronto è significativo.", "Nome del modello configurato."),
        note("Dimostrazione stateless", "Le due chiamate sono indipendenti: la seconda non riceve il primo messaggio. Non è un difetto del modello, ma dell'input fornito.", "Il modello dichiara di non conoscere il nome. La forma esatta varia."),
        note("Agente con checkpointer", "`InMemorySaver` conserva lo stato per chiave di configurazione. È adatto alla lezione; un processo reale usa storage persistente.", "Nessun output. `agente` espone memoria breve per thread."),
        note("Stesso thread, memoria condivisa", "Le due invocazioni usano lo stesso `thread_id`. Il checkpointer ricostruisce la cronologia prima della seconda chiamata.", "Una risposta che ricorda il nome `Nico`."),
        note("Thread diverso, isolamento", "Cambiare identificatore crea una conversazione separata. Questo confine evita che informazioni di utenti o sessioni diverse si mescolino.", "Il modello non conosce il nome nella nuova conversazione."),
        note("Store di lungo termine", "Un dizionario simula memoria esterna al thread. I tool rendono esplicita la decisione di salvare o recuperare, anziché memorizzare automaticamente tutto.", "Nessun output. `STORE` è vuoto e i due tool sono disponibili."),
        note("Scrittura della preferenza", "L'agente riceve istruzione esplicita di usare `ricorda`. Il dato sopravvive alla creazione di un nuovo agente perché vive nello store esterno.", "`Store dopo il salvataggio:` seguito da una coppia chiave/valore relativa alla preferenza."),
        note("Recupero tra conversazioni", "Un nuovo agente non ha la cronologia precedente, ma può interrogare lo store. È la differenza tra memoria conversazionale e memoria durevole.", "Una risposta che riferisce la preferenza per elenchi puntati."),
        note("Scoperta e trace della memoria", "Il tool `elenca_memoria` permette al nuovo agente di scoprire quali chiavi sono disponibili prima di recuperarne una. Il trace rende osservabili richiesta del tool, risultato e risposta finale.", "La chiave salvata compare nell'elenco; il trace mostra le chiamate a `elenca_memoria` e `richiama`, quindi una risposta che recupera la preferenza."),
    ],
    "04": [
        note("Setup del notebook", "Configurazione e chiave vengono validate prima di creare coordinatore e subagente.", "Percorso `.env` caricato."),
        note("Modello condiviso", "Il modello base alimenta coordinatore e ricercatore; il router potrà sostituirlo con un modello più forte per richieste selezionate.", "Nome del modello base."),
        note("Piano come stato esplicito", "Il tool non si limita a restituire testo: aggiorna `PIANO`, rendendo i passi ispezionabili dal programma e dallo studente.", "Nessun output. La lista è inizialmente vuota."),
        note("Subagente incapsulato come tool", "Il ricercatore ha prompt e cronologia separati. Il coordinatore vede solo domanda e sintesi, riducendo inquinamento del contesto principale.", "Nessun output. `chiedi_al_ricercatore` è ora uno strumento delegabile."),
        note("Middleware di model routing", "Il middleware intercetta ogni richiesta e può sostituire il modello senza cambiare il graph. L'euristica è volutamente semplice per rendere visibile il punto di estensione.", "Nessun output. Testi con `architettura`, `complesso` o `approfondito` useranno `model_forte`."),
        note("Coordinatore", "Il prompt definisce ordine operativo: pianificare, delegare quando utile, sintetizzare. Tool e middleware vengono assemblati in un unico agente.", "Nessun output. `coordinatore` è pronto."),
        note("Lettura della trace", "L'helper rende leggibili messaggi, tool call e risultati senza nascondere deleghe. Evidenzia quando il coordinatore invoca il ricercatore e produce un riepilogo quantitativo.", "Nessun output. `stampa_messaggi_run` è pronta per mostrare trace e subagenti del run successivo."),
        note("Esecuzione coordinata", "La richiesta richiede sia piano sia delega. Alla fine si osservano risposta naturale e stato `PIANO`, due rappresentazioni complementari del lavoro.", "Una sintesi sulle due librerie e una lista di passi registrata. Dettagli dipendono dal modello."),
    ],
    "05": [
        note("Setup", "Il notebook valida ambiente e chiave prima di introdurre effetti collaterali simulati.", "Percorso `.env` caricato."),
        note("Modello", "Il client viene configurato una sola volta e non conserva lato provider la conversazione.", "Nome del modello pronto."),
        note("Effetto collaterale simulato", "Il tool registra email in memoria invece di inviarle. Questo permette di studiare audit e verifica senza contattare servizi esterni.", "Nessun output. `INVIATE` è vuota."),
        note("Audit middleware", "Il middleware registra inizio e fine attorno alla vera esecuzione del tool. Non salva destinatario o testo, riducendo esposizione di dati sensibili.", "Nessun output. `TRACCIA` è vuota e verrà popolata durante la tool call."),
        note("Limite deterministico", "Il limite non dipende dalla buona volontà del modello. Dopo cinque tool call il runtime termina il ciclo secondo la policy configurata.", "Nessun output. `limite` è pronto con `run_limit=5`."),
        note("Assemblaggio dell'harness minimo", "Tool, audit e limite convivono nello stesso graph. Questo mostra che un harness è composizione di policy, non una singola classe.", "Nessun output. `agente` è invocabile."),
        note("Azione richiesta dall'utente", "Il modello interpreta destinatario e contenuto, poi usa il tool. L'invio resta simulato ma segue lo stesso flusso di un effetto reale.", "Conferma dell'email a `mario@example.com`. La formulazione può variare."),
        note("Verifica deterministica", "Si controllano sia trace sia stato concreto. L'assert impedisce di considerare completato un run che non ha prodotto esattamente un effetto.", "Trace `start:invia_email`, `done:invia_email`, una email registrata e messaggio `Verifica superata`."),
    ],
    "06": [
        note("Setup", "Configurazione locale e chiave vengono validate prima dei quattro loop.", "Percorso `.env` caricato."),
        note("Modello", "Un solo client alimenta agente, giudice e analista. In produzione questi ruoli possono usare tier diversi.", "Nome del modello pronto."),
        note("Loop agente di base", "`esegui` nasconde il boilerplate del graph e restituisce solo testo finale. Gli altri loop chiameranno questa funzione.", "Nessun output. Agente e helper sono definiti."),
        note("Schema della rubrica", "Pydantic vincola punteggi tra zero e uno e rende il feedback strutturato. Uno schema chiuso riduce risposte del giudice difficili da interpretare.", "Nessun output. La classe `Giudizio` è disponibile."),
        note("Giudice strutturato", "Il modello viene adattato a restituire `Giudizio`. La soglia rimane codice deterministico, separata dalla valutazione probabilistica.", "Nessun output. `valuta` restituirà `(passa, voto, feedback)`."),
        note("Verification loop", "Prima si produce una risposta, poi la rubrica la valuta. Se non passa, il feedback viene incorporato in un nuovo tentativo anziché ripetere identica richiesta.", "Voto tra `0` e `1`, booleano `passa` e risposta finale. Può comparire una seconda risposta migliorata."),
        note("Parser cron minimale", "Le funzioni implementano wildcard, liste e intervalli `*/n` per minuto e ora. Il sottoinsieme è sufficiente a spiegare il trigger senza dipendere da scheduler esterni.", "Nessun output. `cron_combacia` è pronta per timestamp timezone-aware."),
        note("Event-driven loop", "L'espressione ogni minuto combacia sempre, quindi simula uno scheduler che avvia l'agente automaticamente.", "Una frase generata che conferma l'avvio automatico."),
        note("Schema della proposta", "La whitelist strutturale limita ciò che il loop di miglioramento può cambiare. Campi fuori schema non diventano configurazione attiva.", "Nessun output. `Proposta` consente solo sintesi, addendum e limite tool."),
        note("Analisi propose-only", "L'analista legge un report aggregato e produce una proposta, ma il blocco non la applica. Eval, canary e approvazione vengono prima di ogni promozione reale.", "Sintesi e due override opzionali. Valori possono essere `None` se il modello non trova evidenza sufficiente."),
    ],
    "07": [
        note("Contratti del modello", "Le dataclass distinguono identità, capacità e prezzi. Due provider che espongono la stessa API possono comunque dichiarare feature diverse.", "Nessun output. Sono disponibili profili `cloud` e `local`."),
        note("Capability preflight", "Il controllo rifiuta richieste incompatibili prima di spendere token o avviare lavoro parziale.", "Il cloud passa; il locale stampa `Rifiuto anticipato: unsupported_structured_output`."),
        note("Costo normalizzato", "La stessa formula converte token in costo per qualunque provider. Un modello locale mantiene costo API zero senza perdere le metriche di utilizzo.", "Una riga per provider: costo cloud positivo e costo local pari a `0`."),
        note("Tassonomia degli errori", "Messaggi diversi vengono ridotti a categorie operative e flag retryable. Il runner può reagire senza conoscere ogni SDK.", "`Tassonomia verificata`; gli assert devono passare."),
    ],
    "08": [
        note("Misura del contesto", "I messaggi vengono classificati e stimati. Separare contenuto ricostruibile permette di scegliere offload prima di un riassunto costoso.", "Dizionario con circa `total=2175` e `reconstructible=2000`."),
        note("Policy di riduzione", "La decisione usa rapporto di riempimento e quantità ricostruibile. L'ordine rende esplicito perché si preferisce offload a compaction.", "`Azione: offload`; l'assert passa."),
        note("Offload con integrità", "Il contenuto completo finisce su file; nel contesto resta riferimento, checksum ed estratto. Il checksum viene verificato subito.", "Una riga `[offloaded]` con path temporaneo, SHA-256 abbreviato ed estratto."),
        note("Ledger preventivo", "La prenotazione valuta massimo teorico prima della chiamata; `settle` registra consumo effettivo. Questo evita sforamenti dovuti a call concorrenti.", "Rappresentazione di `Ledger` con `used_tokens=2300` e costo calcolato."),
    ],
    "09": [
        note("Schema durevole", "SQLite conserva lavoro e interrupt. Stati terminali distinti evitano l'ambiguità di un generico `completed=false`.", "Nessun output. Tabelle create quando `open_store` viene chiamata."),
        note("Idempotenza e claim", "`enqueue` riusa una chiave già vista; `claim` cambia stato con controllo versione. Sono i nuclei di deduplicazione e optimistic locking.", "Nessun output. Helper definiti."),
        note("Restart simulato", "La connessione viene chiusa mentre esiste un interrupt pending. Alla riapertura, decisione e transizione terminale riprendono dallo storage.", "Un dizionario con id, `state='completed'` e versione incrementata."),
    ],
    "10": [
        note(
            "Profili e task",
            """
            **Problema che risolviamo.** Se il piano dice solo «manda il lavoro a `researcher`»,
            il runtime non sa se quel nome può davvero scrivere file o usare la sandbox. Il nome
            è un'etichetta; i permessi devono stare nei dati.

            **Cosa definisce il blocco.**

            - `Profile`: un agente del roster. Ha `capabilities` (es. `research`, `python`),
              `tools` (es. `browser`, `sandbox`) e `read_only` (se `True` non può scrivere).
            - `Task`: un pezzo di lavoro. Dichiaro **requisiti** (`capabilities`, `tools`,
              `writes`), una scelta preferita (`agent`) e alternative (`alternatives`), più
              eventuali `depends_on` (altri task da completare prima).

            **Cosa osservare nel roster.** Tre ruoli diversi:

            | Nome | Può | Tool | Scrive? |
            |------|-----|------|---------|
            | `researcher` | research | browser | no |
            | `builder` | python | sandbox | sì |
            | `reviewer` | review | — | no |

            Il messaggio didattico: il router **propone** un nome; il validatore **verifica**
            contro questi campi. Non si deduce «`builder` suona come chi scrive codice» dal nome.
            """,
            """
            Nessun output a schermo. Dopo l'esecuzione esistono le classi `Profile` e `Task`,
            e il dizionario `roster` con tre chiavi: `researcher`, `builder`, `reviewer`.
            Puoi ispezionare con `roster.keys()` o `roster["builder"]` in una cella temporanea.
            """,
        ),
        note(
            "Assegnazione least-privilege",
            """
            **Idea centrale.** `supports(profile, task)` risponde sì solo se:

            1. ogni capability del task è nel profilo (`task.capabilities <= profile.capabilities`);
            2. ogni tool del task è nel profilo;
            3. se il task deve scrivere (`writes=True`), il profilo **non** è `read_only`.

            `assign` prova prima `task.agent`, poi le `alternatives`, e aggiorna `task.agent`
            solo quando trova un candidato compatibile. Se nessuno va bene, restituisce `None`
            (nessuna delega silenziosa).

            **Scenario di questo blocco (volutamente "sbagliato").** Il router propone
            `researcher` per un task Python che usa `sandbox` e scrive. `researcher` è
            read-only e non ha capability `python`: fallisce. L'alternativa `builder` invece
            passa tutti i controlli. Vedrai stampato `Assegnato a: builder`.

            Questo è il punto del notebook: il modello può sbagliare la proposta; il codice
            corregge (o rifiuta) in modo osservabile.
            """,
            """
            ```text
            Assegnato a: builder
            ```

            Gli `assert` passano in silenzio. Se vedi un `AssertionError`, probabilmente non hai
            eseguito la cella del roster, oppure hai modificato i profili.
            """,
        ),
        note(
            "DAG e review indipendente",
            """
            **Parte A — cicli.** Se il task `a` dipende da `b` e `b` dipende da `a`,
            l'orchestratore non sa da dove partire: è un deadlock logico. `has_cycle` fa una
            visita in profondità (DFS): se mentre esplora un nodo lo reincontra sulla
            catena corrente (`visiting`), c'è un ciclo. Il primo esempio costruisce apposta
            `a ↔ b` e verifica che venga rilevato.

            **Parte B — review indipendente.** Creiamo un task di tipo `review` che dipende
            da `build`. Il router propone di nuovo `builder` (chi ha costruito), ma il
            validatore, grazie alle alternative e alla capability `review`, assegna
            `reviewer`. L'assert finale controlla anche `review.agent != validated.agent`:
            non basta avere un nome "reviewer" nel piano; deve essere **un agente diverso**
            da chi ha prodotto l'artefatto. Altrimenti è autocertificazione.
            """,
            """
            ```text
            Reviewer indipendente: reviewer
            ```

            Gli `assert` sul ciclo e sull'indipendenza passano senza stampare nulla.
            Se `validated` non esiste, riesegui la sezione 2 nello stesso kernel.
            """,
        ),
        note(
            "Protocollo terminale",
            """
            **Problema.** Un subagente può restituire una frase fluida («tutto ok, test passati»)
            senza allegare nulla di verificabile. In un harness serio quello non basta.

            **Contratto minimale di questo blocco.**

            - `status`: esito dichiarato (qui usiamo `"complete"`);
            - `evidence`: prove osservabili (es. riga di log di pytest);
            - `artifacts`: percorsi o nomi di file prodotti.

            `terminal_report` **rifiuta** `status="complete"` se `evidence` è vuota: solleva
            `ValueError`. Evidenze e artefatti non sono opzionali nel caso di successo; sono
            parte del messaggio di fine lavoro. (Prova a chiamare
            `terminal_report("complete", [], [])` in una cella a parte: deve fallire.)
            """,
            """
            Qualcosa di equivalente a:

            ```text
            {'status': 'complete', 'evidence': ['pytest: 12 passed'], 'artifacts': ['report.md']}
            ```

            Se chiami `terminal_report("complete", [], [])` ottieni `ValueError: complete richiede evidenza`.
            Quello è il comportamento corretto, non un bug.
            """,
        ),
    ],
    "11": [
        note("Costruzione del manifest", "JSON canonico e SHA-256 collegano goal, risposta e artefatti. Ordinamento stabile rende il digest riproducibile.", "Nessun output. Helper per digest e manifest sono definiti."),
        note("Tamper detection", "La prima verifica passa; dopo la modifica del file lo stesso manifest non corrisponde più al workspace.", "`Tampering rilevato`; entrambi gli assert passano."),
        note("Snapshot indipendente", "Il checker legge una copia read-only. Una modifica successiva al workspace non altera retroattivamente ciò che è stato controllato.", "`Checker separato: True`."),
        note("Gate di delivery", "Successo tecnico non basta per pubblicare. Il gate richiede congiunzione di integrità, CI, preview, rollback e decisione umana.", "`Gate verificato`; scenario incompleto fallisce e scenario completo passa."),
    ],
    "12": [
        note("Risultati paired", "Baseline e candidato condividono gli stessi case id, così ogni regressione è attribuibile. Le metriche aggregate non sostituiscono il confronto caso per caso.", "Due dizionari: candidato con pass rate maggiore, meno token e latenza minore."),
        note("Regression gate", "Il gate blocca regressioni anche quando la media migliora. Impone inoltre tetti per token e latenza.", "Dizionario con `passed=True`, lista regressioni vuota e token ratio inferiore a uno."),
        note("Canary stabile", "Hash della sessione assegna sempre lo stesso arm. La distribuzione su molte sessioni approssima la frazione configurata.", "Conteggi vicini a 800 baseline e 200 canary, con variazione deterministica dovuta agli hash."),
        note("Promotion e rollback", "Ogni modifica salva eventi append-only. Il rollback è una nuova transizione e non cancella la storia della promozione.", "Lista di eventi e configurazione attiva tornata a `max_tool_calls=12`."),
    ],
}


EXTRAS: dict[str, list[ExtraExample]] = {
    "01": [
        ExtraExample("Esempio aggiuntivo: testare il tool senza modello", "Prima di attribuire un errore all'agente, conviene verificare direttamente funzione e validazione degli argomenti.", """
for misure in ({"base": 3, "altezza": 2}, {"base": -1, "altezza": 4}):
    try:
        print(misure, "->", area_rettangolo.invoke(misure))
    except ValueError as errore:
        print(misure, "-> errore:", errore)
""", "Il primo caso stampa `6.0`; il secondo mostra l'errore sulle misure positive."),
        ExtraExample("Esempio aggiuntivo: osservare il prompt prima della chiamata", "Formattare il prompt senza invocare il modello permette di controllare esattamente quali messaggi verranno inviati.", """
anteprima = prompt.format_messages(argomento="un dizionario Python")
for messaggio in anteprima:
    print(type(messaggio).__name__, "->", messaggio.content)
""", "Due righe: istruzione del tutor e richiesta con `un dizionario Python`. Nessuna chiamata API aggiuntiva."),
    ],
    "02": [
        ExtraExample("Esempio aggiuntivo: tabella di path consentiti e vietati", "Provare più forme evita una difesa costruita su un solo caso noto.", """
for nome in ("report.txt", "cartella/dati.csv", "../segreto.txt", "/tmp/fuori.txt"):
    try:
        print(nome, "-> OK:", percorso_sicuro(nome))
    except ValueError as errore:
        print(nome, "-> BLOCCATO:", errore)
""", "I primi due path restano nel workspace; `../segreto.txt` e `/tmp/fuori.txt` vengono bloccati."),
        ExtraExample("Esempio aggiuntivo: distinguere successo ed errore del processo", "Exit code e stderr sono segnali più affidabili di una frase del modello.", """
print(esegui_python.invoke({"codice": "print(sum(range(6)))"}))
print(esegui_python.invoke({"codice": "raise RuntimeError('demo')"}))
""", "Prima esecuzione: `exit=0` e stdout `15`. Seconda: exit diverso da zero e traceback in stderr."),
    ],
    "03": [
        ExtraExample("Esempio aggiuntivo: aggiornamento e chiave assente", "Una memoria utile deve definire comportamento per sovrascrittura e mancata corrispondenza.", """
print(ricorda.invoke({"chiave": "formato", "valore": "tabella"}))
print(ricorda.invoke({"chiave": "formato", "valore": "elenco"}))
print("formato:", richiama.invoke({"chiave": "formato"}))
print("lingua:", richiama.invoke({"chiave": "lingua"}))
""", "La seconda scrittura sostituisce la prima; `formato` vale `elenco`, mentre `lingua` restituisce il fallback."),
        ExtraExample("Esempio aggiuntivo: ispezionare il checkpoint", "Dopo le invocazioni è possibile leggere lo stato senza chiedere di nuovo al modello.", """
stato = agente.get_state(config)
messaggi_salvati = stato.values.get("messages", [])
print("Messaggi nel thread 1:", len(messaggi_salvati))
print("Ultimo tipo:", type(messaggi_salvati[-1]).__name__)
""", "Numero maggiore di zero e ultimo tipo normalmente `AIMessage`. Nessuna chiamata API aggiuntiva."),
    ],
    "04": [
        ExtraExample("Esempio aggiuntivo: piano verificabile senza agente", "Testare il tool direttamente mostra che il piano è vero stato applicativo, non solo testo generato.", """
print(imposta_piano.invoke({"passi": ["raccogli criteri", "confronta opzioni", "verifica conclusione"]}))
assert PIANO[-1] == "verifica conclusione"
print("Passi registrati:", len(PIANO))
""", "Tre righe del piano e `Passi registrati: 3`; l'assert deve passare."),
        ExtraExample("Esempio aggiuntivo: delega diretta e contesto isolato", "Invocare il tool-subagente separatamente rende visibile il suo contratto: una domanda entra, una sintesi ristretta esce.", """
sintesi = chiedi_al_ricercatore.invoke({
    "domanda": "Indica tre criteri per confrontare librerie Python, senza scegliere una libreria."
})
print(sintesi)
""", "Tre punti concisi, per esempio manutenzione, API e prestazioni. Il testo varia e comporta una chiamata modello."),
    ],
    "05": [
        ExtraExample("Esempio aggiuntivo: verifier riutilizzabile", "Estrarre la verifica in una funzione consente di applicare lo stesso contratto a run diversi.", """
def verifica_email(registro: list[dict], destinatario: str) -> tuple[bool, str]:
    corrispondenze = [item for item in registro if item["a"] == destinatario]
    if len(corrispondenze) != 1:
        return False, f"attese 1 email, trovate {len(corrispondenze)}"
    return True, "una sola email al destinatario corretto"

print(verifica_email(INVIATE, "mario@example.com"))
print(verifica_email(INVIATE, "assente@example.com"))
""", "Prima tupla `(True, ...)`; seconda `(False, 'attese 1 email, trovate 0')`."),
        ExtraExample("Esempio aggiuntivo: decisione HITL esplicita", "La decisione umana deve essere un dato verificabile e legato all'azione, non una frase vaga nel prompt.", """
def applica_decisione(azione: dict, decisione: str) -> str:
    if decisione not in {"approve", "reject"}:
        raise ValueError("decisione non valida")
    return "ESEGUITA" if decisione == "approve" else "BLOCCATA"

azione = {"tool": "invia_email", "destinatario": "mario@example.com"}
print("approve ->", applica_decisione(azione, "approve"))
print("reject  ->", applica_decisione(azione, "reject"))
""", "`approve -> ESEGUITA` e `reject -> BLOCCATA`."),
    ],
    "06": [
        ExtraExample("Esempio aggiuntivo: matrice di trigger cron", "Una tabella di casi rende evidente la differenza tra wildcard, step e ora specifica.", """
momento = datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc)
for espressione in ("* * * * *", "*/15 * * * *", "0 10 * * *", "30 10 * * *"):
    print(espressione, "->", cron_combacia(espressione, momento))
""", "Risultati: `True`, `True`, `False`, `True` per il timestamp delle 10:30."),
        ExtraExample("Esempio aggiuntivo: gate deterministico per una proposta", "La proposta del modello non viene applicata direttamente. Un gate controlla limiti e campi consentiti.", """
def proposta_ammissibile(valore: Proposta) -> tuple[bool, list[str]]:
    problemi = []
    if valore.max_chiamate_tool is not None and not 1 <= valore.max_chiamate_tool <= 50:
        problemi.append("max_chiamate_tool fuori intervallo")
    if valore.aggiunta_al_prompt and len(valore.aggiunta_al_prompt) > 500:
        problemi.append("aggiunta_al_prompt troppo lunga")
    return not problemi, problemi

print(proposta_ammissibile(Proposta(max_chiamate_tool=20)))
print(proposta_ammissibile(Proposta(max_chiamate_tool=500)))
""", "Prima proposta ammessa; seconda respinta con problema sul limite tool."),
    ],
    "07": [
        ExtraExample("Esempio aggiuntivo: matrice delle capability", "Confrontare profili in tabella rende evidente quali task richiedono fallback o escalation.", """
for candidato in (cloud, local):
    cap = candidato.capabilities
    print(candidato.name, {"tools": cap.tools, "structured": cap.structured_output, "parallel": cap.parallel_tools})
""", "Il profilo cloud mostra tutte le capability vere; quello locale conserva structured output e parallel tools disabilitati."),
        ExtraExample("Esempio aggiuntivo: policy di retry", "La tassonomia diventa utile quando guida una decisione operativa coerente.", """
for messaggio in ("HTTP 429 rate limit", "request timeout", "401 invalid API key", "maximum context reached"):
    categoria, retry = classify_error(messaggio)
    azione = "retry con backoff" if retry else "stop o correzione configurazione"
    print(categoria, "->", azione)
""", "Rate limit e timeout producono retry; auth e context length producono stop/correzione."),
    ],
    "08": [
        ExtraExample("Esempio aggiuntivo: osservare tutte le soglie", "Una matrice di riempimento mostra che la policy cambia in base a pressione e ricostruibilità.", """
for totale_demo, ricostruibile_demo in ((500, 0), (1900, 0), (1900, 900), (2500, 900)):
    print(totale_demo, ricostruibile_demo, "->", decide(totale_demo, 2400, ricostruibile_demo))
""", "Nell'ordine: `keep`, `compact`, `offload`, `stop`."),
        ExtraExample("Esempio aggiuntivo: rifiuto preventivo del budget", "Il caso negativo verifica che una chiamata troppo grande venga bloccata prima di consumare risorse.", """
ledger_piccolo = Ledger(1_000, Decimal("0.01"))
try:
    ledger_piccolo.reserve(900, 500, Decimal("1"), Decimal("6"))
except RuntimeError as errore:
    print("Bloccato prima della chiamata:", errore)
""", "`Bloccato prima della chiamata: budget_exceeded`."),
    ],
    "09": [
        ExtraExample("Esempio aggiuntivo: deduplicare una richiesta", "La stessa chiave idempotente deve restituire lo stesso identificatore anche se il payload del retry differisce.", """
with TemporaryDirectory() as temporary:
    db = open_store(Path(temporary) / "idem.sqlite")
    primo = enqueue(db, "utente:richiesta-7", {"tentativo": 1})
    secondo = enqueue(db, "utente:richiesta-7", {"tentativo": 2})
    print("stesso id:", primo == secondo, primo)
    db.close()
""", "`stesso id: True` seguito da un UUID."),
        ExtraExample("Esempio aggiuntivo: optimistic locking", "Due worker non devono completare lo stesso item usando la stessa versione letta in precedenza.", """
with TemporaryDirectory() as temporary:
    db = open_store(Path(temporary) / "lock.sqlite")
    run_id = enqueue(db, "lock-demo", {})
    item = claim(db, "worker-a")
    versione = item["version"]
    prima = db.execute("UPDATE work SET state='completed', version=version+1 WHERE id=? AND version=?", (run_id, versione)).rowcount
    seconda = db.execute("UPDATE work SET state='completed', version=version+1 WHERE id=? AND version=?", (run_id, versione)).rowcount
    print("prima transizione:", prima, "seconda obsoleta:", seconda)
    db.close()
""", "`prima transizione: 1 seconda obsoleta: 0`."),
    ],
    "10": [
        extra(
            "Esempio aggiuntivo: nessun agente compatibile",
            """
            **Perché importa.** In produzione è tentante "forzare" un'assegnazione comunque
            (es. dare il task al primo agente disponibile). Qui facciamo l'opposto: se nessuno
            nel roster soddisfa i requisiti, `assign` restituisce `None`.

            **Lettura del task.** `deploy` chiede capability `python`, tool `sandbox` e
            `writes=True`. Candidati: `researcher` (read-only, no python) e `reviewer`
            (no python, no sandbox). Nessuno passa `supports` → nessuna delega.

            Messaggio da ricordare: **fallire in modo esplicito** è meglio di una delega
            che viola least privilege.
            """,
            """
            # Nessun candidato nel roster può: python + sandbox + scrittura.
            impossibile = Task("deploy", "researcher", ["reviewer"], {"python"}, {"sandbox"}, True)
            print("Assegnazione:", assign(impossibile))
            """,
            """
            ```text
            Assegnazione: None
            ```

            `None` qui è successo didattico: il validatore ha rifiutato invece di forzare.
            Se stampasse un nome agente, avresti una violazione di least privilege.
            """,
        ),
        extra(
            "Esempio aggiuntivo: ciclo indiretto",
            """
            **Scenario.** Tre task:

            - `a` dipende da `b`
            - `b` dipende da `c`
            - `c` dipende da `a`

            Nessuna freccia è un auto-loop a due nodi, ma insieme formano un ciclo.
            `has_cycle` deve percorrere tutto il grafo (DFS / visite) e restituire `True`.

            In un planner generato da LLM questo è frequente: ogni passo "sembra" locale e
            ragionevole, ma l'insieme non è eseguibile. Il validatore deve vedere il piano
            intero, non solo i vicini di un nodo.
            """,
            """
            # a → b → c → a: ciclo a tre nodi (indiretto).
            ciclo_lungo = [
                Task("a", "builder", [], set(), set(), False, depends_on=["b"]),
                Task("b", "builder", [], set(), set(), False, depends_on=["c"]),
                Task("c", "reviewer", [], set(), set(), False, depends_on=["a"]),
            ]
            print("Ciclo rilevato:", has_cycle(ciclo_lungo))
            """,
            """
            ```text
            Ciclo rilevato: True
            ```

            Se ottenessi `False`, il rilevatore starebbe controllando solo archi diretti
            e perderebbe i cicli lunghi — bug tipico da evitare in produzione.
            """,
        ),
    ],
    "11": [
        ExtraExample("Esempio aggiuntivo: approvazione legata all'hash", "Una decisione umana deve valere solo per la versione esatta del dossier controllato.", """
def approval_valid(gate: dict, manifest: dict) -> bool:
    return gate.get("decision") == "approved" and gate.get("manifest_sha256") == manifest["manifest_sha256"]

with TemporaryDirectory() as temporary:
    workspace = Path(temporary)
    (workspace / "a.txt").write_text("v1")
    manifest = build_manifest("deploy", "pronto", workspace, ["a.txt"])
    gate = {"decision": "approved", "manifest_sha256": manifest["manifest_sha256"]}
    print("prima:", approval_valid(gate, manifest))
    manifest_modificato = {**manifest, "manifest_sha256": "nuovo-hash"}
    print("dopo modifica:", approval_valid(gate, manifest_modificato))
""", "`prima: True` e `dopo modifica: False`."),
        ExtraExample("Esempio aggiuntivo: gate quasi completo", "Il caso più pericoloso è assumere che sette condizioni su otto siano sufficienti.", """
condizioni = dict(integrity=True, checker=True, branch="feature/x", clean=True, ci=True, preview=True, rollback=True, approved=False)
print("Senza approvazione:", delivery_ready(**condizioni))
condizioni["approved"] = True
print("Con approvazione:", delivery_ready(**condizioni))
""", "`False` senza approvazione e `True` dopo aver soddisfatto anche l'ultima condizione."),
    ],
    "12": [
        ExtraExample("Esempio aggiuntivo: media migliore con una regressione", "Il confronto paired impedisce che un guadagno medio nasconda un caso precedentemente corretto diventato errato.", """
candidato_con_regressione = [Result("a", False, 50, 80), Result("b", True, 50, 80), Result("c", True, 50, 80)]
print(gate(baseline, candidato_con_regressione))
""", "`passed=False` e `regressions=['a']`, anche se token e latenza sono migliori."),
        ExtraExample("Esempio aggiuntivo: cambiare la frazione canary", "La stessa funzione permette di confrontare rollout prudente e rollout più ampio mantenendo assegnazione stabile per sessione.", """
for frazione in (0.05, 0.20, 0.50):
    selezionate = sum(arm(f"session-{i}", frazione) == "canary" for i in range(2_000))
    print(frazione, "->", selezionate)
""", "Conteggi vicini rispettivamente a 100, 400 e 1000. Sono deterministici per questi session id."),
    ],
}


LAB_INTROS: dict[str, str] = {
    "10": """
    ## Laboratorio aggiuntivo

    Gli esempi seguenti riusano `assign` e `has_cycle` definiti sopra: **non riavviare**
    il kernel a meno che non sia necessario. Il primo caso mostra un rifiuto netto
    (nessun agente compatibile); il secondo un ciclo più lungo di due nodi, tipico
    bug quando le dipendenze vengono generate automaticamente.
    """,
}

RECAPS: dict[str, str] = {
    "10": """
    ## Riepilogo e troubleshooting

    **Cosa hai visto in quattro punti.**

    1. **Contratti espliciti** — profilo e task dichiarano capability, tool e scrittura.
    2. **Least privilege** — il validatore corregge o rifiuta la proposta del router.
    3. **DAG + review indipendente** — niente cicli; chi costruisce non autocertifica.
    4. **Protocollo terminale** — `complete` senza evidenze non è accettabile.

    Prima di passare al notebook successivo, prova a spiegare a voce: *chi* ha deciso
    l'assegnazione (codice, non modello), *perché* `researcher` è stato scartato, e
    *cosa* rende osservabile un esito `complete`.

    Se una cella fallisce:

    1. rileggi l'output atteso e individua la prima invariante non rispettata;
    2. verifica di aver eseguito tutte le celle precedenti **nello stesso kernel**;
    3. questo notebook è offline: non serve `.env` né quota API;
    4. riavvia il kernel solo dopo aver annotato cosa stavi ispezionando;
    5. non "correggere" un caso negativo (`None`, ciclo, `ValueError`): è parte della lezione.
    """,
}

DEFAULT_LAB_INTRO = """
## Laboratorio aggiuntivo

Gli esempi seguenti riusano quanto costruito sopra. Il primo amplia il caso normale; il
secondo esercita un confine, un errore o una proprietà che spesso causa bug reali.
"""

DEFAULT_RECAP = """
## Riepilogo e troubleshooting

Prima di proseguire, prova a spiegare con parole tue: quale stato è cambiato, quale
componente ha preso la decisione e quale prova rende osservabile l'esito.

Se una cella fallisce:

1. rileggi l'output atteso e individua la prima invariante non rispettata;
2. verifica di aver eseguito tutte le celle precedenti nello stesso kernel;
3. per i notebook live, controlla `.env`, modello disponibile e quota API;
4. riavvia il kernel solo dopo aver conservato eventuali file che vuoi ispezionare;
5. non correggere un caso negativo: l'errore previsto è parte dell'esempio.
"""


OVERVIEWS: dict[str, str] = {
    "01": "Passerai da una singola inferenza a una chain e infine a un agente con tool. Durata indicativa: 25–35 minuti. Le risposte del modello non sono deterministiche; gli output strutturali sono invece prevedibili.",
    "02": "Costruirai tool testabili, un workspace confinato e un esecutore con timeout. Durata: 30–40 minuti. Il sottoprocesso è didattico e non sostituisce Docker contro codice ostile.",
    "03": "Confronterai assenza di memoria, checkpoint per thread e memoria esterna. Durata: 25–35 minuti. Osserva sempre quale confine conserva ciascun dato.",
    "04": "Renderai piano e delega osservabili, poi inserirai un router di modello. Durata: 30–40 minuti. L'euristica di routing è volutamente semplice, non una raccomandazione production.",
    "05": "Assemblerai tool con effetto, audit, limite e verifica. Durata: 25–35 minuti. L'email resta simulata: nessun messaggio viene inviato davvero.",
    "06": "Studierai verification, trigger e improvement loop. Durata: 35–45 minuti. Proposta non significa applicazione: il gate resta separato.",
    "07": "Costruirai un contratto provider-neutral con capability, costi ed errori. Durata: 20–30 minuti. Tutto gira offline con standard library.",
    "08": "Distinguerai budget della finestra e budget cumulativo del run. Durata: 25–35 minuti. Tutto gira offline.",
    "09": "Simulerai coda durevole, idempotenza, restart e locking con SQLite. Durata: 25–35 minuti. Tutto gira offline.",
    "10": """Alla fine di questo notebook saprai:

- leggere un **profilo** (cosa un agente può fare) e un **task** (cosa serve fare);
- capire perché un'assegnazione sbagliata viene rifiutata o corretta;
- riconoscere un **ciclo di dipendenze** (DAG = grafo diretto aciclico);
- distinguere una risposta "plausibile" da un esito **verificabile** con prove.

**Durata:** 25–35 minuti. **Prerequisiti:** aver visto i notebook su planning/subagenti
(04) e harness (05). **Modalità:** tutto offline, senza modello. Se un `assert` fallisce,
rileggi l'output atteso prima di riavviare il kernel.""",
    "11": "Costruirai una catena di evidenza, rileverai tampering e separerai successo da delivery. Durata: 25–35 minuti. Tutto gira offline.",
    "12": "Confronterai baseline/candidato, canary e rollback. Durata: 25–35 minuti. Tutto gira offline e produce risultati deterministici.",
}


def tags(cell: nbformat.NotebookNode) -> set[str]:
    return set(cell.get("metadata", {}).get("tags", []))


def generated_cell(cell: nbformat.NotebookNode) -> bool:
    return bool(tags(cell) & GENERATED_TAGS)


def stable_id(path: Path, kind: str, index: int) -> str:
    raw = f"{path.name}:{kind}:{index}".encode()
    return hashlib.sha1(raw).hexdigest()[:20]


def markdown(source: str, *, tag: str, cell_id: str) -> nbformat.NotebookNode:
    cell = nbformat.v4.new_markdown_cell(dedent(source).strip())
    cell.metadata["tags"] = [tag]
    cell["id"] = cell_id
    return cell


def code_cell(source: str, *, cell_id: str) -> nbformat.NotebookNode:
    cell = nbformat.v4.new_code_cell(dedent(source).strip())
    cell.metadata["tags"] = ["didactic-example"]
    cell["id"] = cell_id
    return cell


def enrich(path: Path) -> None:
    prefix = path.name[:2]
    notebook = nbformat.read(path, as_version=4)
    original = [cell for cell in notebook.cells if not generated_cell(cell)]
    code_count = sum(cell.cell_type == "code" for cell in original)
    notes = BLOCK_NOTES[prefix]
    if len(notes) != code_count:
        raise RuntimeError(
            f"{path.name}: {code_count} celle codice ma {len(notes)} annotazioni."
        )

    enriched: list[nbformat.NotebookNode] = []
    code_index = 0
    for cell_index, cell in enumerate(original):
        cell["id"] = stable_id(path, "base", cell_index)
        if cell.cell_type == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        enriched.append(cell)
        if cell_index == 0:
            overview_body = dedent(OVERVIEWS[prefix]).strip()
            reading_mode = dedent(
                """
                Ogni blocco di codice è preceduto da una spiegazione e seguito da un **output
                atteso**. Quando interviene un modello, l'output atteso descrive proprietà e
                invarianti, non una frase letterale. Esegui le celle in ordine e non saltare i
                casi negativi: mostrano il confine del meccanismo, non un incidente del corso.
                """
            ).strip()
            enriched.append(
                markdown(
                    "## Obiettivi, prerequisiti e modalità di lettura\n\n"
                    f"{overview_body}\n\n{reading_mode}",
                    tag="didactic-comment",
                    cell_id=stable_id(path, "overview", 0),
                )
            )
        if cell.cell_type != "code":
            continue
        current = notes[code_index]
        enriched.insert(
            len(enriched) - 1,
            markdown(
                f"### Spiegazione del blocco · {current.title}\n\n{current.explanation}",
                tag="didactic-comment",
                cell_id=stable_id(path, "explanation", code_index),
            ),
        )
        enriched.append(
            markdown(
                f"### Output atteso\n\n{current.expected}",
                tag="didactic-comment",
                cell_id=stable_id(path, "expected", code_index),
            )
        )
        code_index += 1

    enriched.append(
        markdown(
            LAB_INTROS.get(prefix, DEFAULT_LAB_INTRO),
            tag="didactic-example",
            cell_id=stable_id(path, "lab", 0),
        )
    )
    for extra_index, extra in enumerate(EXTRAS[prefix]):
        enriched.extend(
            [
                markdown(
                    f"## {extra.title}",
                    tag="didactic-example",
                    cell_id=stable_id(path, "extra-title", extra_index),
                ),
                markdown(
                    f"### Spiegazione del blocco\n\n{extra.explanation}",
                    tag="didactic-example",
                    cell_id=stable_id(path, "extra-explanation", extra_index),
                ),
                code_cell(
                    extra.source,
                    cell_id=stable_id(path, "extra-code", extra_index),
                ),
                markdown(
                    f"### Output atteso\n\n{extra.expected}",
                    tag="didactic-example",
                    cell_id=stable_id(path, "extra-expected", extra_index),
                ),
            ]
        )

    enriched.append(
        markdown(
            RECAPS.get(prefix, DEFAULT_RECAP),
            tag="didactic-comment",
            cell_id=stable_id(path, "recap", 0),
        )
    )
    notebook.cells = enriched
    notebook.metadata["didactic_contract"] = {
        "version": 1,
        "explanation_before_every_code": True,
        "expected_output_after_every_code": True,
        "extra_examples": 2,
    }
    nbformat.write(notebook, path)


def main() -> None:
    paths = sorted(NOTEBOOKS.glob("*.ipynb"))
    if len(paths) != 12:
        raise RuntimeError(f"Attesi 12 notebook, trovati {len(paths)}.")
    for path in paths:
        enrich(path)
        print("ENRICHED", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
