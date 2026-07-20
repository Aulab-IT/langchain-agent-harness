/* Navigazione dell'artefatto del manuale.
 *
 * Il modello sta tutto nella pagina, ma si rende UNA pagina alla volta: incorporare
 * quindici documenti e quattrocento snippet nel DOM significherebbe sessantamila nodi
 * all'apertura. Gli snippet si materializzano al primo click e restano.
 */

(() => {
  const model = JSON.parse(document.getElementById("model").textContent);
  const pages = model.pages;
  const bySlug = new Map(pages.map((p) => [p.slug, p]));
  const rail = document.getElementById("rail");
  const main = document.getElementById("main");
  const search = document.getElementById("q");

  /* Aperta da `file://`, alcuni browser negano `localStorage` sollevando: senza questa
     protezione l'eccezione ucciderebbe l'intero script al caricamento e la pagina
     resterebbe bianca. Le preferenze sono un di più; la lettura del manuale no. */
  const store = {
    get(key) {
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(key, value);
      } catch {
        /* preferenza non memorizzata: la sessione corrente funziona lo stesso */
      }
    },
  };

  /* --- radice locale: il percorso assoluto della macchina che ha generato la pagina non
     esiste su quella che la legge. Si tiene relativo e si ricostruisce qui. --- */
  const ROOT_KEY = "handbook:root";
  const localRoot = () => store.get(ROOT_KEY) || model.root;

  /* --- indice di ricerca ------------------------------------------------------------ */

  const index = pages.map((p) => ({
    slug: p.slug,
    title: p.title,
    unit: p.unit,
    haystack: [
      p.title,
      p.unit,
      p.stage,
      ...p.headings.map((h) => h.text),
      ...p.anchors.map((a) => a.file),
      p.text,
    ]
      .join(" ")
      .toLowerCase(),
    files: [...new Set(p.anchors.map((a) => a.file))],
    headings: p.headings,
  }));

  function score(entry, needle) {
    let total = 0;
    if (entry.title.toLowerCase().includes(needle)) total += 8;
    if (entry.unit.toLowerCase().includes(needle)) total += 8;
    if (entry.files.some((f) => f.toLowerCase().includes(needle))) total += 4;
    if (entry.headings.some((h) => h.text.toLowerCase().includes(needle))) total += 4;
    if (entry.haystack.includes(needle)) total += 1;
    return total;
  }

  /* --- rail: L1 e L2 sono la navigazione, non due pagine da leggere ----------------- */

  /* L'unità porta il suo posto nell'ordine: `4.2` sta nello stadio 4 e viene dopo `4.1`.
     Ordinare per nome di file darebbe un rail alfabetico, che non è informazione. */
  function rank(page) {
    const match = /^(\d+)\.(\d+)/.exec(page.unit);
    if (match) return [0, Number(match[1]), Number(match[2])];
    if (/^T\./.test(page.unit)) return [1, 0, Number(page.unit.slice(2)) || 0];
    return [-1, 0, 0];
  }

  function groupKey(page) {
    if (page.kind === "index") return "il-manuale";
    const match = /^(\d+)\./.exec(page.unit);
    if (match) return `stadio-${match[1]}`;
    return /^T\./.test(page.unit) ? "trasversale" : "unita";
  }

  function buildRail() {
    const groups = new Map();
    const sorted = [...pages].sort((a, b) => {
      const [ra, sa, ua] = rank(a);
      const [rb, sb, ub] = rank(b);
      return ra - rb || sa - sb || ua - ub;
    });
    for (const page of sorted) {
      const key = groupKey(page);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(page);
    }

    // Lo stesso stadio è descritto in modo diverso da pagine diverse («stadio 4» e
    // «stadio 4 · esecuzione guardata degli effetti collaterali»): si tiene la più
    // descrittiva invece di stampare due gruppi che sono lo stesso gruppo.
    const labels = new Map();
    for (const [key, items] of groups) {
      const best = items
        .map((p) => p.stage)
        .filter(Boolean)
        .sort((a, b) => b.length - a.length)[0];
      labels.set(key, key === "il-manuale" ? "Il manuale" : best || "Unità");
    }

    rail.textContent = "";

    const mapHead = document.createElement("p");
    mapHead.className = "rail-group";
    mapHead.textContent = "Colpo d'occhio";
    const mapButton = document.createElement("button");
    mapButton.className = "rail-item";
    mapButton.type = "button";
    mapButton.dataset.slug = MAP_SLUG;
    const mapIcon = document.createElement("span");
    mapIcon.className = "uid";
    mapIcon.textContent = "◍";
    const mapName = document.createElement("span");
    mapName.textContent = "Mappa";
    mapButton.append(mapIcon, mapName);
    mapButton.addEventListener("click", () => go(MAP_SLUG));
    rail.append(mapHead, mapButton);

    for (const [key, items] of groups) {
      const label = labels.get(key);
      const head = document.createElement("p");
      head.className = "rail-group";
      head.textContent = label;
      rail.append(head);
      for (const page of items) {
        const button = document.createElement("button");
        button.className = "rail-item";
        button.type = "button";
        button.dataset.slug = page.slug;
        const uid = document.createElement("span");
        uid.className = "uid";
        uid.textContent = page.unit || "";
        const name = document.createElement("span");
        name.textContent = page.title.replace(/^L\d\s*·\s*/, "");
        const count = document.createElement("span");
        count.className = "n";
        if (page.anchors.length) count.textContent = page.anchors.length;
        button.append(uid, name, count);
        button.addEventListener("click", () => go(page.slug));
        rail.append(button);
      }
    }
  }

  function markCurrent(slug) {
    for (const item of rail.querySelectorAll(".rail-item")) {
      item.setAttribute("aria-current", item.dataset.slug === slug ? "true" : "false");
    }
  }

  /* --- snippet ---------------------------------------------------------------------- */

  function editorHref(file, line) {
    if (model.editor === "none") return null;
    const scheme = model.editor === "cursor" ? "cursor" : "vscode";
    return `${scheme}://file/${localRoot()}/${file}:${line}`;
  }

  function buildSnippet(view) {
    const data = model.snippets[view.snippet];
    const box = document.createElement("div");
    box.className = "snippet";

    const bar = document.createElement("div");
    bar.className = "bar";
    const path = document.createElement("span");
    path.className = "path";
    path.textContent = `${data.file}:${data.start}${data.end !== data.start ? "–" + data.end : ""}`;
    bar.append(path);

    const spacer = document.createElement("span");
    spacer.className = "sp";
    bar.append(spacer);

    const href = editorHref(data.file, data.start);
    if (href) {
      const open = document.createElement("a");
      open.href = href;
      open.textContent = "apri nell'editor";
      bar.append(open);
    }

    // Non è un accessorio: se la CSP blocca gli schemi custom, questo resta l'unico modo
    // di arrivare al file.
    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = "copia percorso";
    copy.addEventListener("click", async () => {
      const text = `${data.file}:${data.start}`;
      try {
        await navigator.clipboard.writeText(text);
        copy.textContent = "copiato";
      } catch {
        // Clipboard negata: si seleziona, così resta un Cmd-C di distanza.
        const field = document.createElement("input");
        field.value = text;
        box.append(field);
        field.select();
        copy.textContent = "seleziona e copia";
      }
      setTimeout(() => (copy.textContent = "copia percorso"), 1800);
    });
    bar.append(copy);
    box.append(bar);

    const pre = document.createElement("pre");
    const code = document.createElement("code");
    data.lines.forEach((line, offset) => {
      const number = data.first + offset;
      const cited = number >= data.start && number <= data.end;
      const row = document.createElement(cited ? "span" : "span");
      if (cited) row.className = "cited";
      const gutter = document.createElement("span");
      gutter.className = "ln";
      gutter.textContent = data.elided ? "" : number;
      row.append(gutter, document.createTextNode(line + "\n"));
      code.append(row);
    });
    pre.append(code);
    box.append(pre);
    return box;
  }

  function wireAnchors(page) {
    for (const button of main.querySelectorAll("button.anchor")) {
      button.addEventListener("click", () => {
        const open = button.getAttribute("aria-expanded") === "true";
        const existing = button.nextElementSibling;
        if (open && existing && existing.classList.contains("snippet")) {
          existing.remove();
          button.setAttribute("aria-expanded", "false");
          return;
        }
        const view = page.anchors.find((a) => String(a.snippet) === button.dataset.snippet);
        if (!view) return;
        button.after(buildSnippet(view));
        button.setAttribute("aria-expanded", "true");
      });
    }
  }

  /* --- mappa: un comportamento, molti siti ------------------------------------------
   *
   * Il grafo dice la cosa che la prosa non riesce a mostrare: quali file sono condivisi
   * da più unità. Un file con molti archi è un punto in cui comportamenti diversi si
   * toccano — cioè dove una modifica ne rompe più di uno.
   */

  // Nessuna pagina del manuale può chiamarsi così: gli slug vengono dai nomi dei file.
  const MAP_SLUG = "mappa";
  let mapState = null;

  function graphData(showFiles) {
    const nodes = [];
    const links = [];
    const byId = new Map();
    const add = (node) => {
      byId.set(node.id, node);
      nodes.push(node);
      return node;
    };

    for (const page of pages) {
      if (page.kind !== "unit") continue;
      const stageId = "s:" + groupKey(page);
      if (!byId.has(stageId)) {
        add({ id: stageId, kind: "stage", label: page.stage.split("·")[0].trim(), r: 9 });
      }
      const unit = add({
        id: "u:" + page.slug,
        kind: "unit",
        label: page.unit || page.title,
        title: page.title.replace(/^L\d\s*·\s*/, ""),
        slug: page.slug,
        r: 6 + Math.min(9, Math.sqrt(page.anchors.length) * 1.6),
      });
      links.push({ a: stageId, b: unit.id, k: 0.03, len: 90 });

      if (!showFiles) continue;
      for (const file of new Set(page.anchors.map((a) => a.file))) {
        const fileId = "f:" + file;
        if (!byId.has(fileId)) {
          add({
            id: fileId,
            kind: "file",
            label: file.split("/").pop(),
            file,
            r: 4,
            degree: 0,
          });
        }
        byId.get(fileId).degree += 1;
        links.push({ a: unit.id, b: fileId, k: 0.02, len: 60 });
      }
    }

    for (const node of nodes) {
      if (node.kind === "file") node.r = 3.5 + Math.min(8, node.degree * 1.5);
    }
    return { nodes, links, byId };
  }

  function layout(graph, width, height) {
    // Disposizione iniziale a cerchio: partire dal centro esatto lascia le forze senza
    // direzione e il grafo esplode al primo passo.
    graph.nodes.forEach((node, i) => {
      const angle = (i / graph.nodes.length) * Math.PI * 2;
      const radius = node.kind === "stage" ? 60 : node.kind === "unit" ? 160 : 250;
      node.x = width / 2 + Math.cos(angle) * radius;
      node.y = height / 2 + Math.sin(angle) * radius;
      node.vx = 0;
      node.vy = 0;
    });

    for (let step = 0; step < 320; step++) tick(graph, width, height, 1);
  }

  function tick(graph, width, height, damping) {
    const { nodes, links, byId } = graph;
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.hypot(dx, dy) || 0.01;
        const min = a.r + b.r + 14;
        const force = (2400 / (dist * dist)) + (dist < min ? (min - dist) * 0.35 : 0);
        dx /= dist;
        dy /= dist;
        a.vx -= dx * force;
        a.vy -= dy * force;
        b.vx += dx * force;
        b.vy += dy * force;
      }
    }
    for (const link of links) {
      const a = byId.get(link.a);
      const b = byId.get(link.b);
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.hypot(dx, dy) || 0.01;
      const pull = (dist - link.len) * link.k;
      a.vx += (dx / dist) * pull;
      a.vy += (dy / dist) * pull;
      b.vx -= (dx / dist) * pull;
      b.vy -= (dy / dist) * pull;
    }
    for (const node of nodes) {
      if (node.pinned) {
        node.vx = node.vy = 0;
        continue;
      }
      node.vx += (width / 2 - node.x) * 0.004;
      node.vy += (height / 2 - node.y) * 0.004;
      node.vx *= 0.82 * damping;
      node.vy *= 0.82 * damping;
      node.x = Math.max(node.r + 6, Math.min(width - node.r - 6, node.x + node.vx));
      node.y = Math.max(node.r + 6, Math.min(height - node.r - 6, node.y + node.vy));
    }
  }

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function draw(state) {
    const { ctx, graph, width, height, hover, selected } = state;
    const ink = css("--ink");
    const soft = css("--ink-soft");
    const faint = css("--ink-faint");
    const accent = css("--accent");
    const warn = css("--warn");
    const rule = css("--rule");

    ctx.clearRect(0, 0, width, height);

    const near = new Set();
    const focus = hover || selected;
    if (focus) {
      near.add(focus.id);
      for (const link of graph.links) {
        if (link.a === focus.id) near.add(link.b);
        if (link.b === focus.id) near.add(link.a);
      }
    }

    for (const link of graph.links) {
      const a = graph.byId.get(link.a);
      const b = graph.byId.get(link.b);
      const lit = focus && near.has(a.id) && near.has(b.id);
      ctx.strokeStyle = lit ? accent : rule;
      ctx.globalAlpha = focus ? (lit ? 0.9 : 0.25) : 0.7;
      ctx.lineWidth = lit ? 1.6 : 1;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    for (const node of graph.nodes) {
      const dim = focus && !near.has(node.id);
      ctx.globalAlpha = dim ? 0.3 : 1;
      ctx.fillStyle = node.kind === "unit" ? accent : node.kind === "file" ? warn : faint;
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      ctx.fill();

      const label = node.kind === "file" && node.degree < 2 && !near.has(node.id) ? "" : node.label;
      if (label) {
        ctx.fillStyle = node.kind === "unit" ? ink : soft;
        ctx.font = `${node.kind === "unit" ? 600 : 400} 11px ui-sans-serif, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.fillText(label, node.x, node.y - node.r - 5);
      }
    }
    ctx.globalAlpha = 1;
  }

  function nodeAt(state, x, y) {
    for (let i = state.graph.nodes.length - 1; i >= 0; i--) {
      const node = state.graph.nodes[i];
      if (Math.hypot(node.x - x, node.y - y) <= node.r + 5) return node;
    }
    return null;
  }

  function describe(state, node) {
    const box = state.info;
    box.textContent = "";
    if (!node) {
      const hint = document.createElement("p");
      hint.textContent =
        "Ogni cerchio blu è un'unità di comportamento, ogni cerchio ambra un file citato. " +
        "Un file collegato a più unità è un punto in cui comportamenti diversi si toccano.";
      box.append(hint);
      return;
    }

    const title = document.createElement("h2");
    const body = document.createElement("p");
    const list = document.createElement("ul");

    if (node.kind === "unit") {
      const page = bySlug.get(node.slug);
      title.textContent = `${page.unit} · ${node.title}`;
      body.textContent = `${page.anchors.length} ancore · ${
        new Set(page.anchors.map((a) => a.file)).size
      } file citati`;
      const open = document.createElement("button");
      open.className = "link";
      open.type = "button";
      open.textContent = "apri la pagina";
      open.addEventListener("click", () => go(node.slug));
      body.append(" — ", open);
      for (const file of new Set(page.anchors.map((a) => a.file))) {
        const item = document.createElement("li");
        item.textContent = file;
        list.append(item);
      }
    } else if (node.kind === "file") {
      title.textContent = node.label;
      const citing = pages.filter(
        (p) => p.kind === "unit" && p.anchors.some((a) => a.file === node.file)
      );
      body.textContent =
        citing.length === 1
          ? `${node.file} — citato da una sola unità.`
          : `${node.file} — citato da ${citing.length} unità: è un punto di contatto fra comportamenti diversi.`;
      for (const page of citing) {
        const item = document.createElement("li");
        const link = document.createElement("button");
        link.className = "link";
        link.type = "button";
        link.textContent = `${page.unit} · ${page.title.replace(/^L\d\s*·\s*/, "")}`;
        link.addEventListener("click", () => go(page.slug));
        item.append(link);
        list.append(item);
      }
    } else {
      title.textContent = node.label;
      body.textContent = "Stadio del flusso: raggruppa le unità che ne fanno parte.";
    }

    box.append(title, body, list);
  }

  function renderMap() {
    main.textContent = "";
    markCurrent(MAP_SLUG);

    const head = document.createElement("div");
    head.className = "map-head";
    const title = document.createElement("h1");
    title.textContent = "Mappa";
    const opts = document.createElement("div");
    opts.className = "map-opts";
    const toggle = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = true;
    toggle.append(box, document.createTextNode("mostra i file citati"));
    opts.append(toggle);
    head.append(title, opts);

    const wrap = document.createElement("div");
    wrap.id = "canvas-wrap";
    const canvas = document.createElement("canvas");
    canvas.id = "graph";
    wrap.append(canvas);

    const legend = document.createElement("div");
    legend.className = "legend";
    for (const [cls, text] of [
      ["stage", "stadio del flusso"],
      ["unit", "unità di comportamento — l'area cresce con le ancore"],
      ["file", "file citato — l'area cresce con le unità che lo citano"],
    ]) {
      const item = document.createElement("span");
      const dot = document.createElement("i");
      dot.className = `dot ${cls}`;
      item.append(dot, document.createTextNode(text));
      legend.append(item);
    }

    const info = document.createElement("div");
    info.className = "map-info";

    main.append(head, wrap, legend, info);

    const ctx = canvas.getContext("2d");
    const state = { ctx, canvas, info, hover: null, selected: null, graph: null };
    mapState = state;

    function build() {
      const ratio = devicePixelRatio || 1;
      const width = wrap.clientWidth;
      const height = canvas.clientHeight;
      canvas.width = width * ratio;
      canvas.height = height * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      state.width = width;
      state.height = height;
      state.graph = graphData(box.checked);
      layout(state.graph, width, height);
      state.hover = null;
      state.selected = null;
      draw(state);
      describe(state, null);
    }

    box.addEventListener("change", build);

    let dragging = null;
    canvas.addEventListener("mousemove", (event) => {
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      if (dragging) {
        dragging.x = x;
        dragging.y = y;
        for (let i = 0; i < 6; i++) tick(state.graph, state.width, state.height, 1);
        dragging.x = x;
        dragging.y = y;
        draw(state);
        return;
      }
      const node = nodeAt(state, x, y);
      if (node !== state.hover) {
        state.hover = node;
        canvas.style.cursor = node ? "pointer" : "grab";
        draw(state);
      }
    });

    canvas.addEventListener("mousedown", (event) => {
      const rect = canvas.getBoundingClientRect();
      const node = nodeAt(state, event.clientX - rect.left, event.clientY - rect.top);
      if (!node) return;
      dragging = node;
      node.pinned = true;
      canvas.classList.add("grabbing");
    });

    addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging.pinned = false;
      dragging = null;
      canvas.classList.remove("grabbing");
    });

    canvas.addEventListener("click", (event) => {
      const rect = canvas.getBoundingClientRect();
      const node = nodeAt(state, event.clientX - rect.left, event.clientY - rect.top);
      state.selected = node;
      describe(state, node);
      draw(state);
    });

    canvas.addEventListener("dblclick", (event) => {
      const rect = canvas.getBoundingClientRect();
      const node = nodeAt(state, event.clientX - rect.left, event.clientY - rect.top);
      if (node && node.kind === "unit") go(node.slug);
    });

    build();
  }

  /* --- percorsi di lettura: l'ordine è l'informazione ------------------------------- */

  const units = pages.filter((p) => p.kind === "unit");

  function trail(page) {
    const at = units.findIndex((u) => u.slug === page.slug);
    if (at < 0) return null;
    const box = document.createElement("nav");
    box.className = "trail";
    if (at > 0) {
      const prev = document.createElement("button");
      prev.type = "button";
      prev.textContent = "← " + units[at - 1].title.replace(/^L\d\s*·\s*/, "");
      prev.addEventListener("click", () => go(units[at - 1].slug));
      box.append(prev);
    }
    const spacer = document.createElement("span");
    spacer.className = "sp";
    box.append(spacer);
    if (at < units.length - 1) {
      const next = document.createElement("button");
      next.type = "button";
      next.textContent = units[at + 1].title.replace(/^L\d\s*·\s*/, "") + " →";
      next.addEventListener("click", () => go(units[at + 1].slug));
      box.append(next);
    }
    return box;
  }

  /* --- routing ---------------------------------------------------------------------- */

  function render(slug, hash) {
    if (slug === MAP_SLUG) return renderMap();
    mapState = null;
    const page = bySlug.get(slug) || pages[0];
    main.innerHTML = page.html;
    wireAnchors(page);
    const tail = trail(page);
    if (tail) main.append(tail);
    markCurrent(page.slug);
    if (hash) {
      const target = main.querySelector(`[id="${CSS.escape(hash)}"]`);
      if (target) target.scrollIntoView();
    } else {
      main.scrollIntoView();
    }
  }

  function go(slug, hash) {
    location.hash = `#/${slug}` + (hash ? `#${hash}` : "");
  }

  function fromHash() {
    const raw = location.hash.replace(/^#\//, "");
    if (!raw) return render(pages[0].slug);
    const [slug, hash] = raw.split("#");
    render(slug, hash);
  }

  /* --- ricerca ---------------------------------------------------------------------- */

  function showResults(needle) {
    const hits = index
      .map((entry) => ({ entry, points: score(entry, needle) }))
      .filter((h) => h.points > 0)
      .sort((a, b) => b.points - a.points);

    main.textContent = "";
    const title = document.createElement("h1");
    title.textContent = `${hits.length} risultati per «${needle}»`;
    main.append(title);

    if (!hits.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Nessuna unità cita questo termine.";
      main.append(empty);
      return;
    }

    for (const { entry } of hits) {
      const hit = document.createElement("button");
      hit.className = "hit";
      hit.type = "button";
      const name = document.createElement("div");
      name.textContent = entry.title;
      const where = document.createElement("div");
      where.className = "where";
      const cited = entry.files.filter((f) => f.toLowerCase().includes(needle));
      where.textContent = cited.length ? `cita ${cited.join(", ")}` : entry.unit || entry.slug;
      hit.append(name, where);
      hit.addEventListener("click", () => {
        search.value = "";
        go(entry.slug);
      });
      main.append(hit);
    }
  }

  search.addEventListener("input", () => {
    const needle = search.value.trim().toLowerCase();
    if (needle.length < 2) return fromHash();
    showResults(needle);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && document.activeElement !== search) {
      event.preventDefault();
      search.focus();
    } else if (event.key === "Escape" && document.activeElement === search) {
      search.value = "";
      search.blur();
      fromHash();
    }
  });

  /* --- tema ------------------------------------------------------------------------- */

  const THEME_KEY = "handbook:theme";
  const stored = store.get(THEME_KEY);
  if (stored) document.documentElement.dataset.theme = stored;
  document.getElementById("theme").addEventListener("click", () => {
    const dark =
      document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme &&
        matchMedia("(prefers-color-scheme: dark)").matches);
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set(THEME_KEY, next);
  });

  buildRail();
  addEventListener("hashchange", fromHash);
  fromHash();
})();
