import {
  BrainCircuit,
  Cog,
  File as FileIcon,
  Layers,
  Sparkles,
  User,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ComponentType } from "react";
import { getSessionContext } from "../../api";
import type { ContextData, ContextEntry } from "../../types";
import { Spinner } from "../shared/PanelEmpty";

const KIND_META: Record<string, { label: string; icon: ComponentType<{ size?: number }> }> = {
  system: { label: "Sistema", icon: Cog },
  memory: { label: "Memoria", icon: BrainCircuit },
  user: { label: "Utente", icon: User },
  assistant: { label: "Agente", icon: Sparkles },
  tool: { label: "Tool", icon: Wrench },
  other: { label: "Altro", icon: FileIcon },
};

function kindMeta(kind: string) {
  return KIND_META[kind] ?? KIND_META.other;
}

export function ContextModal({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<ContextData | null>(null);
  const [error, setError] = useState("");
  const [kinds, setKinds] = useState<Set<string>>(new Set());
  const [category, setCategory] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    getSessionContext(sessionId)
      .then((value) => !cancelled && setData(value))
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "Caricamento contesto fallito"),
      );
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const presentKinds = useMemo(() => {
    const set = new Set<string>();
    for (const entry of data?.entries ?? []) set.add(entry.kind);
    return [...set];
  }, [data]);

  const filtered = useMemo<ContextEntry[]>(() => {
    const term = search.trim().toLowerCase();
    return (data?.entries ?? []).filter((entry) => {
      if (kinds.size && !kinds.has(entry.kind)) return false;
      if (category && entry.category !== category) return false;
      if (term) {
        const haystack = `${entry.text} ${entry.name ?? ""} ${entry.tool_calls
          .map((call) => `${call.name} ${call.args}`)
          .join(" ")}`.toLowerCase();
        if (!haystack.includes(term)) return false;
      }
      return true;
    });
  }, [data, kinds, category, search]);

  const shownTokens = filtered.reduce((sum, entry) => sum + entry.tokens, 0);

  const toggleKind = (kind: string) =>
    setKinds((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  const resetFilters = () => {
    setKinds(new Set());
    setCategory(null);
    setSearch("");
  };

  const hasFilter = kinds.size > 0 || category !== null || search.trim() !== "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="presentation"
      onClick={onClose}
    >
      <section
        className="flex max-h-[90vh] w-full max-w-5xl flex-col rounded-xl border border-border bg-surface shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="Contesto dell'agente"
        onClick={(event) => event.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center gap-4 border-b border-border px-6 py-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
            <Layers size={20} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold">Contesto dell'agente</h2>
            <p className="text-xs text-muted">
              {data
                ? `≈ ${data.total_tokens.toLocaleString("it-IT")} token stimati · ${
                    data.entries.length
                  } voci · finestra ${Math.round(data.context_window / 1000)}k · snapshot ultimo run`
                : "Caricamento…"}
            </p>
          </div>
          <button
            type="button"
            className="rounded-lg p-2 text-muted hover:bg-surface-raised hover:text-foreground"
            aria-label="Chiudi"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>

        {error ? (
          <div className="p-6 text-sm text-danger">{error}</div>
        ) : !data ? (
          <div className="flex flex-1 items-center justify-center p-10">
            <Spinner label="Carico il contesto…" />
          </div>
        ) : (
          <>
            {/* Stats + filters */}
            <div className="shrink-0 space-y-3 border-b border-border px-6 py-4">
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-raised">
                <div className="flex h-full">
                  {data.categories.map((cat) => (
                    <button
                      key={cat.name}
                      type="button"
                      title={`${cat.name} · ${cat.tokens} token`}
                      className="h-full transition-opacity hover:opacity-80"
                      style={{ width: `${cat.percent}%`, background: cat.color }}
                      onClick={() =>
                        setCategory((current) => (current === cat.name ? null : cat.name))
                      }
                    />
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {data.categories.map((cat) => (
                  <button
                    key={cat.name}
                    type="button"
                    onClick={() =>
                      setCategory((current) => (current === cat.name ? null : cat.name))
                    }
                    className={`flex items-center gap-2 rounded-lg border px-2.5 py-1 text-xs ${
                      category === cat.name
                        ? "border-accent bg-accent/10 text-foreground"
                        : "border-border text-muted hover:text-foreground"
                    }`}
                  >
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: cat.color }} />
                    {cat.name}
                    <span className="font-mono text-muted-2">{cat.percent}%</span>
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {presentKinds.map((kind) => {
                  const meta = kindMeta(kind);
                  const Icon = meta.icon;
                  const active = kinds.has(kind);
                  return (
                    <button
                      key={kind}
                      type="button"
                      onClick={() => toggleKind(kind)}
                      className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs ${
                        active
                          ? "border-accent bg-accent/10 text-foreground"
                          : "border-border text-muted hover:text-foreground"
                      }`}
                    >
                      <Icon size={13} />
                      {meta.label}
                    </button>
                  );
                })}
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Cerca nel contesto…"
                  className="ml-auto min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-1.5 text-xs outline-none focus:border-accent sm:max-w-xs"
                />
                {hasFilter ? (
                  <button
                    type="button"
                    onClick={resetFilters}
                    className="rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted hover:text-foreground"
                  >
                    Azzera
                  </button>
                ) : null}
              </div>
            </div>

            {/* Entries */}
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-4">
              {filtered.length ? (
                filtered.map((entry) => {
                  const meta = kindMeta(entry.kind);
                  const Icon = meta.icon;
                  const color =
                    data.categories.find((cat) => cat.name === entry.category)?.color ?? "#596273";
                  return (
                    <article
                      key={entry.index}
                      className="overflow-hidden rounded-lg border border-border bg-surface-raised/30"
                      style={{ borderLeft: `3px solid ${color}` }}
                    >
                      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-xs">
                        <Icon size={14} />
                        <strong className="font-medium">{meta.label}</strong>
                        {entry.name ? (
                          <span className="font-mono text-muted">{entry.name}</span>
                        ) : null}
                        <span
                          className="rounded px-1.5 py-0.5"
                          style={{ background: `${color}22`, color }}
                        >
                          {entry.category}
                        </span>
                        <span className="ml-auto font-mono text-muted-2">{entry.tokens} tok</span>
                      </div>
                      {entry.text ? (
                        <pre className="max-h-72 overflow-auto whitespace-pre-wrap px-3 py-2 font-mono text-xs leading-relaxed text-foreground/85">
                          {entry.text}
                        </pre>
                      ) : null}
                      {entry.tool_calls.length ? (
                        <div className="space-y-1 border-t border-border px-3 py-2">
                          {entry.tool_calls.map((call, callIndex) => (
                            <div key={callIndex} className="font-mono text-xs">
                              <span className="text-accent">→ {call.name}</span>
                              <span className="text-muted">({call.args})</span>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  );
                })
              ) : (
                <div className="py-16 text-center text-sm text-muted">
                  Nessuna voce con i filtri correnti.
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="shrink-0 border-t border-border px-6 py-3 text-xs text-muted">
              {filtered.length} / {data.entries.length} voci mostrate ·{" "}
              {shownTokens.toLocaleString("it-IT")} token
            </div>
          </>
        )}
      </section>
    </div>
  );
}
