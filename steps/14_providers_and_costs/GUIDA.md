# Step 14 — Provider, capability e costi

## Obiettivo

Separare il comportamento dell’harness dal vendor del modello. Lo step mostra tre contratti:
identità del provider, capacità dichiarate e uso normalizzato. Nessuna chiamata di rete viene
eseguita: il catalogo e il preflight sono verificabili offline.

## Perché serve

Una stringa come `model_name` non dice se il modello supporta tool paralleli, output strutturato,
reasoning, caching o reporting dei token. Se queste differenze emergono solo durante un run, il
fallimento arriva tardi e può lasciare lavoro parziale. `ModelDescriptor` rende tali capacità
esplicite; `ProviderRegistry` concentra la costruzione degli SDK ai bordi del sistema.

Il costo è normalizzato nello stesso modo per provider cloud e locali. Per i modelli cloud il
catalogo converte token input/output in valuta. Per i provider locali il costo API può essere
zero, ma il consumo di token resta osservabile.

## Esecuzione

```bash
uv run python steps/14_providers_and_costs/app.py
```

Osserva che il profilo locale parte conservativo: capacità non verificate restano disabilitate.
Il tentativo di costruire OpenAI senza chiave fallisce nel preflight con tassonomia `auth`, senza
avviare un run. Cambia i prezzi demo e verifica come varia il costo normalizzato.

## Passo successivo

Una volta note finestra, costo e capacità, l’harness può assegnare budget reali a contesto e run.
