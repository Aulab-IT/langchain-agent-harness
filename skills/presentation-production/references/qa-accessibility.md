# QA visuale e accessibilità

## Passaggio diagnostico
1. Verifica che il `.pptx` si apra come pacchetto ZIP/OOXML.
2. Esegui `scripts/validate_pptx.py deck.pptx --report qa.json`.
3. Risolvi titoli assenti/duplicati, testo troppo denso, immagini senza verifica descrittiva e avvisi link/contrasto.
4. Renderizza in PDF/PNG se LibreOffice è disponibile, ispeziona tutte le slide e renderizza di nuovo dopo le correzioni.

```bash
soffice --headless --convert-to pdf --outdir work deck.pptx
pdftoppm -jpeg -r 150 work/deck.pdf work/slide
```

## Ispezione visuale
- Nessun testo tagliato, overlap o oggetto contro il bordo.
- Card, icone e label si allineano alla stessa griglia.
- Il takeaway è comprensibile in 3–5 secondi.
- Immagini nitide e non distorte.
- Grafici con takeaway, unità, periodo, fonte e label leggibili.
- Non affidare distinzioni a solo rosso/verde, posizione o testo minuscolo.
- Verifica ogni hyperlink.

## Passaggio manuale in PowerPoint
1. Apri il deck, controlla font substitution, drift, link e slideshow.
2. Esegui **Review → Check Accessibility** e risolvi/documenta ogni finding.
3. Inserisci alt text significativo per immagini, diagrammi e grafici informativi; marca decorative le decorazioni.
4. Verifica reading order: titolo → evidenza → fonte/footer.
5. Per i grafici fornisci lo stesso insight in alt text, note o narrativa adiacente.
6. Fornisci caption/transcript per video e non rendere essenziale alcuna animazione.

## Contrasto
WCAG 2.2 è uno standard web, non una certificazione PowerPoint. Usalo come riferimento pratico: testo normale ≥4.5:1, testo grande ≥3:1, elementi grafici significativi ≥3:1 dove applicabile. Verifica le vere coppie foreground/background, incluse quelle su immagini.

## Registro di consegna
Registra runtime/generatore, data dei dati, report automatico, stato rendering, Accessibility Checker, revisore/data ed eccezioni. Non definire il deck “WCAG-certified” senza valutazione formale applicabile.