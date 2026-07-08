import { useEffect, useRef, useState } from "react";
import { Check, ChevronsUpDown, Plus, Search } from "lucide-react";
import { relativeLabel } from "../../lib/format";
import type { SessionSummary } from "../../types";

export function SessionSwitcher({
  sessions,
  activeSessionId,
  activeTitle,
  search,
  onSearch,
  onSelect,
  onNew,
}: {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  activeTitle: string | null;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    searchRef.current?.focus();
    const onDoc = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <p className="mb-1.5 px-1 text-xs font-medium uppercase tracking-wide text-muted-2">
        Sessione attiva
      </p>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2.5 rounded-lg border border-border bg-surface-raised px-3 py-2.5 text-left transition-colors hover:border-muted-2"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-foreground">
            {activeTitle ?? "Nessuna sessione"}
          </span>
          <span className="block truncate text-xs text-muted">
            {sessions.length} sessioni · cambia o cerca
          </span>
        </span>
        <ChevronsUpDown size={16} className="shrink-0 text-muted" />
      </button>

      {open ? (
        <div className="absolute left-0 right-0 z-50 mt-1.5 flex max-h-[60vh] flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl">
          <div className="border-b border-border p-2">
            <label className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
              <Search size={15} className="shrink-0 text-muted" />
              <input
                ref={searchRef}
                className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-2"
                aria-label="Cerca sessioni"
                value={search}
                onChange={(event) => onSearch(event.target.value)}
                placeholder="Cerca sessioni"
              />
            </label>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
            {sessions.length ? (
              sessions.map((item) => {
                const active = item.id === activeSessionId;
                return (
                  <button
                    type="button"
                    key={item.id}
                    onClick={() => {
                      onSelect(item.id);
                      setOpen(false);
                    }}
                    className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
                      active
                        ? "bg-accent/10 text-foreground"
                        : "text-muted hover:bg-surface-raised hover:text-foreground"
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{item.title}</span>
                      <span className="block truncate text-xs text-muted">
                        {relativeLabel(item.updated_at)}
                      </span>
                    </span>
                    {item.last_status === "running" ? (
                      <span className="h-2 w-2 shrink-0 rounded-full bg-success" />
                    ) : null}
                    {active ? <Check size={15} className="shrink-0 text-accent" /> : null}
                  </button>
                );
              })
            ) : (
              <p className="px-3 py-6 text-center text-sm text-muted">Nessuna sessione</p>
            )}
          </div>

          <div className="border-t border-border p-2">
            <button
              type="button"
              onClick={() => {
                onNew();
                setOpen(false);
              }}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent hover:bg-accent-soft"
            >
              <Plus size={17} />
              Nuova sessione
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
