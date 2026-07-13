import {
  Bot,
  ChevronDown,
  Database,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  createSubagent,
  deleteSubagent,
  getSubagent,
  listSubagents,
  listTools,
  updateSubagent,
} from "../../api";
import type { ModelTier, Subagent, SubagentDetail, ToolDescriptor } from "../../types";

type Draft = {
  name: string;
  description: string;
  system_prompt: string;
  model_tier: ModelTier;
  capabilities: string;
  inputs: string;
  outputs: string;
  constraints: string;
  tools: string[];
  read_only: boolean;
};

type ToolGroup = {
  id: string;
  label: string;
  hint: string;
  tools: ToolDescriptor[];
};

const EMPTY: Draft = {
  name: "",
  description: "",
  system_prompt: "",
  model_tier: "low",
  capabilities: "",
  inputs: "",
  outputs: "",
  constraints: "",
  tools: [],
  read_only: false,
};

function draftOf(item: SubagentDetail): Draft {
  return {
    name: item.name,
    description: item.description,
    system_prompt: item.system_prompt,
    model_tier: item.model_tier,
    capabilities: item.capabilities.join("\n"),
    inputs: item.inputs.join("\n"),
    outputs: item.outputs.join("\n"),
    constraints: item.constraints.join("\n"),
    tools: item.tools,
    read_only: item.read_only,
  };
}

function routingLines(value: string): string[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean);
}

function RoutingField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return <label className="space-y-1.5">
    <span className="block text-sm font-medium">{label}</span>
    <textarea
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={hint}
      rows={3}
      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent"
    />
    <span className="block text-xs text-muted">Una voce per riga. Usata dal router semantico.</span>
  </label>;
}

function toolGroupOf(tool: ToolDescriptor): Omit<ToolGroup, "tools"> {
  if (tool.origin.startsWith("mcp:")) {
    const server = tool.origin.slice("mcp:".length);
    return { id: `mcp:${server}`, label: `MCP · ${server}`, hint: "Server MCP esterno" };
  }
  if (tool.origin === "local_harness") {
    return { id: "local", label: "Harness locale", hint: "Tool locali: skill e utilità" };
  }
  if (["web_search", "browser_read"].includes(tool.name)) {
    return { id: "web", label: "Web e browser", hint: "Ricerca e lettura fonti pubbliche" };
  }
  if (["docker_exec", "request_user_action"].includes(tool.name)) {
    return { id: "workspace", label: "Workspace e interazione", hint: "Sandbox e azioni utente" };
  }
  return { id: "builtin", label: "Builtin", hint: "Tool base dell'harness" };
}

function groupTools(tools: ToolDescriptor[], query: string): ToolGroup[] {
  const normalized = query.trim().toLocaleLowerCase();
  const visible = tools.filter((tool) =>
    !normalized || `${tool.name} ${tool.summary} ${tool.origin}`.toLocaleLowerCase().includes(normalized),
  );
  const groups = new Map<string, ToolGroup>();
  for (const tool of visible) {
    const group = toolGroupOf(tool);
    const current = groups.get(group.id) ?? { ...group, tools: [] };
    current.tools.push(tool);
    groups.set(group.id, current);
  }
  return [...groups.values()].sort((left, right) => left.label.localeCompare(right.label));
}

function ToolSelector({
  tools,
  selected,
  onToggle,
  onRefresh,
  refreshing,
}: {
  tools: ToolDescriptor[];
  selected: string[];
  onToggle: (name: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const [query, setQuery] = useState("");
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const groups = groupTools(tools, query);
  const visibleNames = groups.flatMap((group) => group.tools.map((tool) => tool.name));
  const allVisibleSelected = visibleNames.length > 0 && visibleNames.every((name) => selected.includes(name));

  const toggleGroup = (id: string) => {
    setClosed((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleVisible = () => {
    for (const name of visibleNames) {
      if (selected.includes(name) === allVisibleSelected) onToggle(name);
    }
  };

  return (
    <div className="space-y-3 rounded-xl border border-border bg-background/30 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">Tool consentiti</p>
          <p className="text-xs text-muted">{selected.length} selezionati · permessi effettivi del subagent</p>
        </div>
        <button
          type="button"
          disabled={!visibleNames.length}
          onClick={toggleVisible}
          className="rounded-lg border border-border px-2.5 py-1.5 text-xs hover:bg-surface-raised disabled:opacity-50"
        >
          {allVisibleSelected ? "Deseleziona visibili" : "Seleziona visibili"}
        </button>
      </div>
      <label className="relative block">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Cerca nome, descrizione o server MCP"
          className="w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm outline-none focus:border-accent"
        />
      </label>
      {groups.length ? groups.map((group) => {
        const isClosed = closed.has(group.id);
        const mcp = group.id.startsWith("mcp:");
        return (
          <section key={group.id} className="overflow-hidden rounded-lg border border-border">
            <button
              type="button"
              onClick={() => toggleGroup(group.id)}
              className="flex w-full items-center gap-2 bg-surface px-3 py-2 text-left hover:bg-surface-raised"
              aria-expanded={!isClosed}
            >
              {mcp ? <Database size={15} className="text-info" /> : <Wrench size={15} className="text-muted" />}
              <span className="flex-1 text-sm font-medium">{group.label}</span>
              <span className="text-xs text-muted">{group.tools.length}</span>
              <ChevronDown size={15} className={`text-muted transition-transform ${isClosed ? "-rotate-90" : ""}`} />
            </button>
            {!isClosed ? <div className="divide-y divide-border"><p className="bg-background/50 px-3 py-1.5 text-xs text-muted">{group.hint}</p>{group.tools.map((tool) => {
              const checked = selected.includes(tool.name);
              return <label key={tool.name} className={`flex cursor-pointer items-start gap-2.5 px-3 py-2.5 transition hover:bg-surface-raised ${checked ? "bg-accent/5" : ""}`}>
                <input type="checkbox" checked={checked} onChange={() => onToggle(tool.name)} className="mt-0.5" />
                <span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><code className="font-mono text-xs font-semibold">{tool.name}</code>{mcp ? <span className="rounded bg-info/10 px-1.5 py-0.5 text-[10px] text-info">MCP</span> : null}</span><span className="mt-0.5 block text-xs leading-relaxed text-muted">{tool.summary || tool.description}</span></span>
              </label>;
            })}</div> : null}
          </section>
        );
      }) : <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-sm text-muted">Nessun tool corrispondente.</p>}
      <div className="flex justify-end border-t border-border pt-3">
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold hover:bg-surface-raised disabled:opacity-50"
          title="Ricarica catalogo tool e server MCP"
        >
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
          Aggiorna tool
        </button>
      </div>
    </div>
  );
}

export function SubagentsView() {
  const [items, setItems] = useState<Subagent[]>([]);
  const [tools, setTools] = useState<ToolDescriptor[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [next, toolList] = await Promise.all([listSubagents(), listTools()]);
      setItems(next);
      setTools(toolList);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Caricamento subagent fallito");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  const toggleTool = (name: string) => {
    setDraft((current) => ({
      ...current,
      tools: current.tools.includes(name)
        ? current.tools.filter((tool) => tool !== name)
        : [...current.tools, name],
    }));
  };

  const save = async () => {
    if (!draft.name.trim() || !draft.description.trim() || !draft.system_prompt.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      if (editing) {
        await updateSubagent(editing, {
          description: draft.description.trim(),
          system_prompt: draft.system_prompt.trim(),
          model_tier: draft.model_tier,
          capabilities: routingLines(draft.capabilities),
          inputs: routingLines(draft.inputs),
          outputs: routingLines(draft.outputs),
          constraints: routingLines(draft.constraints),
          tools: draft.tools,
          read_only: draft.read_only,
        });
      } else {
        await createSubagent({
          ...draft,
          name: draft.name.trim(),
          description: draft.description.trim(),
          system_prompt: draft.system_prompt.trim(),
          capabilities: routingLines(draft.capabilities),
          inputs: routingLines(draft.inputs),
          outputs: routingLines(draft.outputs),
          constraints: routingLines(draft.constraints),
        });
      }
      setDraft(EMPTY);
      setEditing(null);
      setCreating(false);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Salvataggio fallito");
    } finally {
      setBusy(false);
    }
  };

  const edit = async (name: string) => {
    setError("");
    try {
      setDraft(draftOf(await getSubagent(name)));
      setEditing(name);
      setCreating(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Apertura subagent fallita");
    }
  };

  const remove = async (name: string) => {
    if (!window.confirm(`Eliminare il subagent “${name}”?`)) return;
    try {
      await deleteSubagent(name);
      if (editing === name) {
        setEditing(null);
        setCreating(false);
        setDraft(EMPTY);
      }
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Eliminazione fallita");
    }
  };

  return (
    <section className="mx-auto w-full max-w-4xl space-y-4">
      <div className="rounded-xl border border-border bg-surface">
        <div className="flex items-center gap-3 border-b border-border px-6 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-info/20 bg-info/10 text-info"><Bot size={18} /></div>
          <div className="flex-1">
            <h2 className="text-lg font-semibold">Subagent</h2>
            <p className="text-sm text-muted">Ruoli ricaricati dal disco al run successivo. Stesso nome di builtin = override.</p>
          </div>
          {creating || editing ? <button type="button" onClick={() => { setEditing(null); setCreating(false); setDraft(EMPTY); }} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface-raised">Annulla</button> : null}
          <button type="button" onClick={() => { setEditing(null); setCreating(true); setDraft(EMPTY); }} className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-on-accent hover:bg-accent-soft"><Plus size={16} />Nuovo</button>
        </div>
        {error ? <p className="px-6 pt-4 text-sm text-danger">{error}</p> : null}
        {creating || editing ? <div className="space-y-3 border-b border-border p-6">
          <div className="grid gap-3 sm:grid-cols-2">
            <input value={draft.name} disabled={Boolean(editing)} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="nome-kebab" className="rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-accent disabled:opacity-60" />
            <select value={draft.model_tier} onChange={(e) => setDraft({ ...draft, model_tier: e.target.value as ModelTier })} className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent"><option value="low">low</option><option value="mid">mid</option><option value="high">high</option></select>
          </div>
          <input value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} placeholder="Quando usarlo" className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
          <div className="rounded-xl border border-border bg-background/30 p-4">
            <div className="mb-3">
              <p className="text-sm font-semibold">Profilo di routing</p>
              <p className="text-xs text-muted">Descrive il contratto del subagent; nessun match è hardcoded nel codice.</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <RoutingField label="Capacità" hint={"ricerca bibliografica\nanalisi comparativa"} value={draft.capabilities} onChange={(value) => setDraft((current) => ({ ...current, capabilities: value }))} />
              <RoutingField label="Input accettati" hint={"domanda di ricerca\nfile PDF"} value={draft.inputs} onChange={(value) => setDraft((current) => ({ ...current, inputs: value }))} />
              <RoutingField label="Output prodotti" hint={"sintesi con fonti\nreport Markdown"} value={draft.outputs} onChange={(value) => setDraft((current) => ({ ...current, outputs: value }))} />
              <RoutingField label="Vincoli" hint={"non modifica file\nrichiede fonti verificabili"} value={draft.constraints} onChange={(value) => setDraft((current) => ({ ...current, constraints: value }))} />
            </div>
          </div>
          <textarea value={draft.system_prompt} onChange={(e) => setDraft({ ...draft, system_prompt: e.target.value })} placeholder="System prompt" rows={7} className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-accent" />
          <ToolSelector
            tools={tools}
            selected={draft.tools}
            onToggle={toggleTool}
            onRefresh={() => void refresh()}
            refreshing={refreshing}
          />
          <label className="flex items-center gap-2 text-sm text-muted"><input type="checkbox" checked={draft.read_only} onChange={(e) => setDraft({ ...draft, read_only: e.target.checked })} />Solo lettura workspace</label>
          <button type="button" onClick={save} disabled={busy || !draft.name.trim() || !draft.description.trim() || !draft.system_prompt.trim()} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent hover:bg-accent-soft disabled:opacity-50">{busy ? "Salvataggio…" : editing ? "Salva" : "Crea subagent"}</button>
        </div> : null}
        <ul className="divide-y divide-border">{items.map((item) => <li key={item.name} className="flex items-start gap-3 px-6 py-4"><Bot size={18} className="mt-0.5 shrink-0 text-info" /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><code className="font-mono text-sm font-semibold">{item.name}</code><span className="rounded bg-surface-raised px-2 py-0.5 text-xs text-muted">{item.model_tier}</span>{item.read_only ? <span className="rounded bg-surface-raised px-2 py-0.5 text-xs text-muted">read-only</span> : null}{!item.valid ? <span className="text-xs text-danger">{item.errors.join(" · ")}</span> : null}</div><p className="mt-1 text-sm text-muted">{item.description}</p>{item.capabilities.length ? <div className="mt-2 flex flex-wrap gap-1.5">{item.capabilities.map((capability) => <span key={capability} className="rounded bg-info/10 px-2 py-0.5 text-xs text-info">{capability}</span>)}</div> : null}</div><button type="button" onClick={() => void edit(item.name)} className="rounded p-2 text-muted hover:bg-surface-raised hover:text-foreground" aria-label={`Modifica ${item.name}`}><Pencil size={15} /></button><button type="button" onClick={() => void remove(item.name)} className="rounded p-2 text-muted hover:bg-danger/10 hover:text-danger" aria-label={`Elimina ${item.name}`}><Trash2 size={15} /></button></li>)}</ul>
      </div>
    </section>
  );
}
