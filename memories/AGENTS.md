# Memoria dell'agente

Questa memoria viene caricata a ogni avvio.

## Preferenze operative

- Conservare gli artefatti richiesti in `/workspace`.
- Usare nomi di file descrittivi.
- Citare nel report le fonti web usate.
- Prima di concludere, eseguire una verifica riproducibile.

## Apprendimenti

L'agente può aggiornare questa sezione quando una preferenza è davvero durevole e utile
anche in conversazioni future. Non salvare segreti, credenziali o contenuti sensibili.

Mantieni la memoria **concisa**: entra nel prompt a ogni run, quindi ogni riga si paga a
ogni esecuzione futura. Preferisci poche preferenze durature a molte note effimere. Oltre il
limite di dimensione (`HARNESS_MEMORY_MAX_CHARS`, default 32.000 caratteri) il file viene
troncato al termine del run, con un evento `memory.truncated` visibile nel trace.

La promozione al template globale è manuale e **sovrascrive** il template (non fa merge):
prima di promuovere, verifica di voler sostituire per intero la memoria di tutte le sessioni
future.

