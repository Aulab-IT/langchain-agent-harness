---
name: keynote-generator
description: Crea presentazioni Keynote .key da Markdown o PDF usando AppleScript/Keynote su macOS, con branding Aulab, capitoli, note e pipeline verificabile.
---

# Keynote Generator

Genera presentazioni Apple Keynote `.key` a partire da sorgenti Markdown o PDF.

## Quando usarla
- L'utente chiede di creare una presentazione Keynote.
- La sorgente è un file `.md`, `.markdown`, `.pdf`, testo strutturato o appunti.
- Serve un output `.key` apribile su macOS con Keynote, oppure una pipeline pronta da eseguire su Mac.

## Branding obbligatorio
Ogni deck generato con questa skill deve rispettare queste regole:

- Logo watermark: usare sempre il logo Aulab persistente incluso negli assets della skill: `assets/aulab_logo_watermark_48.png.b64`.
- Gli script materializzano automaticamente il logo in `/workspace/work/keynote-generator-assets/aulab_logo_watermark_48.png`.
- Il watermark deve stare in alto a destra, occupare poco spazio e non interferire con titolo, bullet, immagini o tabelle.
- Palette consentita: giallo `#ffed3a`, bianco `#ffffff`, nero `#000000`.
- Slide di contenuto: sfondo bianco, testo nero, watermark in alto a destra.
- Slide capitolo: sfondo giallo `#ffed3a`, testo nero, senza watermark.
- Il deck deve essere organizzato a capitoli.
- Ogni slide deve avere note speaker; se l'input non le contiene, generane una versione sintetica utile per la presentazione.

## Requisiti e limiti
- La creazione nativa `.key` richiede macOS con Keynote installato e accesso ad AppleScript/`osascript`.
- In un container Linux/non-macOS non è possibile verificare l'apertura in Keynote: in quel caso verifica la pipeline fino a `outline.json` e genera anche un `.pptx` di controllo con `scripts/outline_to_pptx.py`.
- Non dipendere dal file allegato `/workspace/aulab_logo_l.png`: il logo deve arrivare dagli assets della skill.
- Per PDF testuali usa `scripts/pdf_to_text.py`; per PDF scansionati/OCR non disponibile, chiedi una sorgente testuale o segnala il limite.

## File di supporto inclusi
- `assets/aulab_logo_watermark_48.png.b64`: logo Aulab persistente, ottimizzato per watermark piccolo.
- `references/deck-template.md`: formato Markdown consigliato per deck con capitoli e note.
- `examples/sample_input.md`: esempio completo di input con capitoli.
- `scripts/materialize_assets.py`: decodifica gli asset della skill nel workspace.
- `scripts/markdown_to_outline.py`: converte Markdown in JSON slide-by-slide applicando branding, capitoli, watermark e note.
- `scripts/pdf_to_text.py`: estrae testo da PDF usando `pypdf` o `PyPDF2` se disponibili.
- `scripts/build_keynote.applescript`: crea un `.key` da `outline.json` su macOS con Keynote.
- `scripts/outline_to_pptx.py`: crea un `.pptx` di fallback/verifica da `outline.json` in ambienti non-macOS.
- `scripts/validate_outline.py`: valida palette, capitoli, watermark, note e logo asset nello `outline.json`.
- `references/verification-checklist.md`: controlli finali.

## Workflow operativo

### 1) Materializza assets
Prima di generare o verificare deck, materializza gli assets della skill:

```bash
python /skills/keynote-generator/scripts/materialize_assets.py
```

Output atteso:
- `/workspace/work/keynote-generator-assets/aulab_logo_watermark_48.png`

### 2) Analisi input
- Identifica il formato sorgente: Markdown, PDF, testo o appunti.
- Estrai titolo principale, capitoli, sezioni, sottopunti, dati/figure/tabelle rilevanti, citazioni o note speaker.
- Se la sorgente non è già divisa in capitoli, crea capitoli logici.
- Se la sorgente è PDF e il testo non è leggibile, segnala il limite e chiedi un file migliore o testo copiabile.

### 3) Progettazione deck
- Crea una mappa slide-by-slide:
  - title slide o primo capitolo;
  - slide capitolo con sfondo giallo e testo nero;
  - slide contenuto con sfondo bianco, testo nero e watermark;
  - closing / next steps.
- Mantieni le slide leggibili: massimo 3-5 bullet quando possibile.
- Usa `references/deck-template.md` come formato normalizzato.

### 4) Da Markdown a outline JSON
Per un Markdown già strutturato:

```bash
python /skills/keynote-generator/scripts/markdown_to_outline.py input.md work/outline.json
python /skills/keynote-generator/scripts/validate_outline.py work/outline.json
```

Output atteso:
- `metadata.logo_asset = assets/aulab_logo_watermark_48.png.b64`
- `metadata.logo_path = /workspace/work/keynote-generator-assets/aulab_logo_watermark_48.png`
- `metadata.palette.yellow = #ffed3a`
- `metadata.palette.white = #ffffff`
- `metadata.palette.black = #000000`
- `slides[]` con `type`, `title`, `bullets`, `notes`, `background`, `text_color`, `watermark`

### 5) Da PDF a testo, poi outline
Se il sorgente è PDF testuale:

```bash
PYTHONPATH=/workspace/.pylib python /skills/keynote-generator/scripts/pdf_to_text.py input.pdf work/source.txt
```

Poi:
1. sintetizza `work/source.txt` in un Markdown conforme a `references/deck-template.md`;
2. assicurati che sia diviso in capitoli con heading tipo `# Capitolo: Nome`;
3. genera `work/outline.json` con `markdown_to_outline.py`;
4. valida con `validate_outline.py`.

### 6) Da outline JSON a Keynote `.key` su macOS
Su Mac con Keynote installato:

```bash
osascript /skills/keynote-generator/scripts/build_keynote.applescript /absolute/path/work/outline.json /absolute/path/output/deck.key
```

Lo script materializza il logo dagli assets della skill e poi:
- apre Keynote;
- crea una presentazione con tema semplice;
- applica sfondo bianco/nero alle slide contenuto;
- applica sfondo giallo `#ffed3a` e testo nero alle slide capitolo;
- aggiunge il logo asset Aulab come watermark piccolo in alto a destra solo sulle slide contenuto;
- inserisce note speaker;
- salva il file `.key`.

### 7) Fallback/verifica PPTX in container non-macOS
Quando non è disponibile Keynote, genera un PPTX verificabile:

```bash
python /skills/keynote-generator/scripts/outline_to_pptx.py work/outline.json output/deck_check.pptx
```

Il PPTX non è il deliverable `.key` finale, ma consente di ispezionare colori, watermark, capitoli e note in modo riproducibile.

### 8) Verifica
Usa `references/verification-checklist.md`.

Verifica minima in container/non-macOS:
```bash
python /skills/keynote-generator/scripts/materialize_assets.py
python /skills/keynote-generator/scripts/markdown_to_outline.py /skills/keynote-generator/examples/sample_input.md /workspace/work/sample_outline.json
python -m json.tool /workspace/work/sample_outline.json >/workspace/work/sample_outline.validated.json
python /skills/keynote-generator/scripts/validate_outline.py /workspace/work/sample_outline.json
python /skills/keynote-generator/scripts/outline_to_pptx.py /workspace/work/sample_outline.json /workspace/output/sample_check.pptx
```

Verifica su macOS:
```bash
osascript /skills/keynote-generator/scripts/build_keynote.applescript /absolute/path/work/outline.json /absolute/path/output/deck.key
test -s /absolute/path/output/deck.key && echo "keynote file created"
```

## Linee guida di stile
- Usa titoli brevi e descrittivi.
- Una slide = un messaggio.
- Lavora sempre a capitoli.
- Evita muri di testo.
- Usa le note speaker per dettagli lunghi.
- Non usare colori diversi da giallo `#ffed3a`, bianco e nero.
- Non richiedere nuovamente il logo se la skill è installata: usa l'asset incluso.

## Report finale richiesto
Quando completi un deck o una pipeline:
- elenca file creati/modificati;
- indica numero slide, capitoli e titoli;
- conferma presenza logo asset e regole watermark/capitoli/note;
- riporta comandi di verifica eseguiti e output reale;
- specifica se il `.key` è stato generato davvero su macOS oppure se l'ambiente corrente consente solo artefatti pronti per l'esecuzione su Mac.
