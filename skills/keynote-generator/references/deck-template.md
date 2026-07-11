# Deck template

Usa questo schema per preparare una presentazione destinata a Keynote con branding Aulab.

```md
---
title: Titolo presentazione
subtitle: Sottotitolo opzionale
author: Nome autore
audience: Pubblico target
source: md|pdf|notes
---

# Capitolo: Introduzione

> Introdurre il capitolo e anticipare i messaggi chiave.

# Slide title
- Bullet 1
- Bullet 2
- Bullet 3

> Speaker note obbligatoria: spiega come presentare questa slide.

# Capitolo: Approfondimento

> Introdurre il cambio di capitolo.

# Sezione successiva
- Punto chiave
- Dato o esempio
- Azione / takeaway

> Speaker note obbligatoria per la slide di contenuto.
```

## Regole visuali obbligatorie
- Il logo Aulab è incluso negli assets della skill: `assets/aulab_logo_watermark_48.png.b64`.
- Gli script lo materializzano in `/workspace/work/keynote-generator-assets/aulab_logo_watermark_48.png`.
- Palette: giallo `#ffed3a`, bianco `#ffffff`, nero `#000000`.
- Slide di contenuto: sfondo bianco, testo nero, logo asset come watermark piccolo in alto a destra.
- Slide capitolo: dichiarate con `# Capitolo: Nome`, sfondo giallo, testo nero, senza watermark.
- Il watermark deve occupare poco spazio e non competere con il contenuto.

## Regole contenuto
- Lavora a capitoli.
- 1 idea principale per slide.
- 3-5 bullet al massimo quando possibile.
- Titoli brevi.
- Ogni slide deve avere note speaker; se mancano, lo script genera note minime automaticamente.
- Usa note per dettagli lunghi, non i bullet.
