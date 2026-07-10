# Verification checklist

Prima di dichiarare conclusa una presentazione Keynote:

## Artefatti
- [ ] File finale `.key` creato in `output/` quando macOS + Keynote sono disponibili.
- [ ] In assenza di Keynote, creato almeno un artefatto intermedio verificabile: `outline.json` e preferibilmente `output/*_check.pptx`.
- [ ] Eventuali file intermedi sono in `work/`, `scripts/` o cartelle non `output/`.

## Branding obbligatorio
- [ ] Palette limitata a giallo `#ffed3a`, bianco `#ffffff`, nero `#000000`.
- [ ] Logo Aulab presente negli assets della skill: `assets/aulab_logo_watermark_48.png.b64`.
- [ ] Logo materializzato come PNG valido in `/workspace/work/keynote-generator-assets/aulab_logo_watermark_48.png`.
- [ ] Slide contenuto: watermark piccolo in alto a destra.
- [ ] Slide capitolo: sfondo giallo, testo nero, nessun watermark.
- [ ] Il watermark non copre titoli, bullet o elementi principali.

## Contenuto
- [ ] Il deck è organizzato a capitoli.
- [ ] Numero slide coerente con la richiesta.
- [ ] Ogni slide ha un titolo.
- [ ] Ogni slide ha note speaker.
- [ ] Ogni slide ha massimo 3-5 bullet salvo eccezioni motivate.
- [ ] Le note speaker contengono dettagli lunghi che non devono comparire in slide.
- [ ] La struttura copre i punti principali del sorgente MD/PDF.

## Verifica tecnica
- [ ] Eseguire `scripts/materialize_assets.py`.
- [ ] Validare JSON/outline con `scripts/validate_outline.py`.
- [ ] Se su macOS: eseguire AppleScript e controllare che il `.key` esista.
- [ ] Se su ambiente non macOS: generare un PPTX di controllo con `scripts/outline_to_pptx.py` e ispezionarlo quando possibile.
- [ ] Verificare sintassi degli script Python con `py_compile`.
- [ ] Dichiarare chiaramente che la generazione `.key` richiede macOS con Keynote se l'ambiente corrente non lo consente.

## Report finale
- [ ] Elencare file creati/modificati.
- [ ] Riportare comando/i di verifica eseguiti e output sintetico reale.
- [ ] Includere istruzioni per aprire o rigenerare il deck.
