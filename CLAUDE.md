# langchain_harness

Harness didattico per agenti, costruito su LangChain/LangGraph. Backend FastAPI +
Control Center React.

## Prima di cercare nel codice, guarda il manuale

`docs/handbook/` descrive questo repo **per comportamento**, non per modulo, e ogni
affermazione porta il punto esatto del codice che la rende vera (`file · L120–140`).

Serve perché un comportamento vive sparso: l'approvazione umana tocca sette siti in due
linguaggi, e il blocco che decide se una conferma vale per una o per tutte le tool call è
`[decision] * decisions_count` — non lo trovi cercando «approvazione».

```
domanda → L1_SISTEMA.md (quale stadio?) → L2_UNITA.md (quale unità?) → L3/<unità>.md
```

Quindici unità, elencate in [`docs/handbook/README.md`](docs/handbook/README.md). Ogni
pagina L3 chiude con **Riepilogo evidenza** (i siti coinvolti) e **Note per chi modifica**
(cosa toccare e quali invarianti non rompere): sono le due sezioni da leggere prima di
cambiare qualcosa.

## Se tocchi un file citato dal manuale

```bash
make handbook          # rilocalizza le ancore e rigenera l'artefatto navigabile
make handbook-check    # gate di CI: verifica che ogni ancora sia dove il manuale dice
```

I numeri di riga non si scrivono a mano: si rigenerano cercando l'impronta di contenuto
registrata in `anchors.lock.json`. Se `--check` riporta `lost`, quel codice non esiste più
e la pagina va riscritta — non è un numero da correggere.

Limite dichiarato: lo strumento verifica il **riferimento**, non la verità. Sa che quel
blocco esiste ancora, non che la frase che lo descrive sia ancora corretta.

## Comandi

```bash
make test              # pytest
make lint              # ruff
make run               # backend + client
make handbook-html     # solo l'artefatto navigabile, in build/handbook/
```

## Da non confondere

`memories/AGENTS.md` è la memoria **dell'agente che l'harness esegue**, montata nel suo
sandbox. Non riguarda te che stai modificando il repo.
