---
name: presentation-production
description: Progetta, genera e verifica presentazioni PowerPoint (.pptx) professionali, accattivanti ed editabili. Usa questa skill ogni volta che l’utente chiede slide, deck, pitch deck, presentazioni executive, template PowerPoint, infografiche, data storytelling, grafici per slide o una revisione del design/accessibilità di una presentazione, anche se fornisce soltanto appunti, un report, dati o un brief. Applica storyboard-first, design system riutilizzabile, componenti grafici nativi, audit di fonti e licenze, diagnostica PPTX e QA manuale di accessibilità.
---

# Presentation Production

Crea presentazioni come un prodotto narrativo, non come una sequenza di bullet decorati. Parti dall’obiettivo del relatore e fai avanzare ogni slide verso una decisione, un insight o un’azione.

## Risorse incluse

| Esigenza | Risorsa |
|---|---|
| Token, griglie e pattern di slide | `references/design-system.md` |
| QA visuale e accessibilità | `references/qa-accessibility.md` |
| Fonti, licenze e attribuzioni | `references/sources-licenses.md` |
| Registro fonti della ricerca | `references/source-register.md` |
| Inventario asset | `assets/ASSET_MANIFEST.json` |
| Storyboard iniziale | `examples/storyboard-template.md` |
| Generare un deck demo editabile | `scripts/build_demo.py` |
| Diagnosticare un PPTX | `scripts/validate_pptx.py deck.pptx --report qa.json` |
| Verificare il manifest asset | `scripts/asset_audit.py assets/ASSET_MANIFEST.json --strict` |
| Verificare il pacchetto della skill | `scripts/check_skill.py .` |

## 1. Definisci il brief

Esplicita pubblico, decisione o azione desiderata, messaggio centrale, tono, durata, formato, lingua, rapporto 16:9/4:3, vincoli di brand, requisiti di editabilità, fonti e accessibilità. Chiedi solo informazioni che cambiano il risultato.

In assenza di istruzioni, usa un deck executive 16:9 editabile di 8–12 slide, con fonti nelle note o in un footer conciso.

Scrivi un throughline in una frase: “Poiché [evidenza], [pubblico] dovrebbe [azione]”. Se è debole, migliora prima la storia, non il layout.

## 2. Crea lo storyboard

Usa questa struttura prima della produzione:

| # | Titolo assertivo / takeaway | Evidenza | Visual | Azione del relatore | Fonte |
|---|---|---|---|---|---|

Mantieni una sola idea dominante per slide. Ordine tipico: contesto → tensione/opportunità → evidenza → implicazione → raccomandazione → azione.

Scegli il visual in base alla domanda: confronto=barre; cambiamento=linea; composizione=barre impilate; relazione=scatter; sequenza=timeline; sistema=processo; decisione=matrice 2×2 o confronto opzioni. Preferisci forme e grafici nativi a infografiche raster per conservare editabilità.

## 3. Applica il design system

Leggi `references/design-system.md`. Definisci sfondo dominante, un accento e colori semantici. Centralizza dimensione slide, margini, scala tipografica, footer e regole di componenti. Non ridurre il font per far entrare il testo: sintetizza, dividi la slide o sposta dettaglio nelle note.

Alterna intenzionalmente hero/KPI, confronto, processo, grafico e conclusione mantenendo griglia, tipografia e ruoli cromatici. Evita card-wall dense, gradienti decorativi e immagini senza funzione informativa.

## 4. Costruisci

Preferisci PptxGenJS se disponibile per un `.pptx` art-directed; usa python-pptx per pipeline dati/report quando adeguato; usa Marp se l’authoring Markdown conta più dell’editabilità nativa. Mantieni codice, dati e metadati fuori da `output/`; inserisci in `output/` soltanto deck e report finali.

Usa helper parametrici per titoli, footer, immagini, KPI, timeline, nodi di processo e grafici. Inserisci alt text e speaker notes quando il motore lo supporta; altrimenti elenca gli interventi manuali richiesti nel report QA. Non dichiarare mai certificata l’accessibilità tramite soli controlli automatici.

## 5. Governa fonti e asset

Prima di usare un’immagine, icona, grafico o dato esterno, registra identificatore, origine, provider, URL, data di recupero, licenza/permesso, modifica, collocazione e attribuzione. Esegui `asset_audit.py`. Non assumere che un risultato di ricerca conceda una licenza.

Preferisci asset del cliente, diagrammi originali, stock con licenza, contenuti Unsplash nei limiti della licenza e Font Awesome Free secondo i termini della versione in uso. Leggi `references/sources-licenses.md`.

## 6. QA e consegna

Esegui `validate_pptx.py` e conserva il JSON risultante. È un controllo diagnostico OOXML: non è una certificazione visuale o di accessibilità.

Renderizza con LibreOffice se disponibile; ispeziona ogni slide a dimensione di presentazione e correggi clipping, overlap, allineamento, whitespace, collisioni di footer, leggibilità di legenda/unità e coerenza. Leggi `references/qa-accessibility.md`.

Prima della consegna, apri in PowerPoint se disponibile, usa Accessibility Checker, verifica reading order, alt text, font, link e slideshow. Dichiara esattamente cosa è stato verificato e gli eventuali limiti di ambiente.

## Formato della risposta finale

Riporta: assunzioni; pubblico/obiettivo/throughline; struttura slide; scelte di design; stato fonti/licenze; file creati; comandi di verifica con risultati; limiti irrisolti.

## Guardrail

- Mantieni un claim principale per slide e rendilo esplicito nel titolo.
- Conserva file e template del cliente; crea nuovi output in directory dedicate.
- Usa WCAG 2.2 come guida pratica, non come certificazione automatica PowerPoint.
- PowerPoint è l’autorità finale per comportamenti specifici e controllo accessibilità.
- Evita animazioni se non chiariscono sequenza o focus; non rendere la comprensione dipendente dal timing.
