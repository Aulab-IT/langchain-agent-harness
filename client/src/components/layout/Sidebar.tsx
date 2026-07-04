import {
  Activity,
  BrainCircuit,
  CircleCheck,
  Code2,
  Gauge,
  Plus,
  Search,
  Settings2,
  Timer,
  TrendingUp,
  X,
} from "lucide-react";
import type { View } from "../../lib/constants";
import { relativeLabel } from "../../lib/format";
import type { SessionSummary } from "../../types";

export function Sidebar({
  open,
  view,
  sessions,
  activeSessionId,
  search,
  onSearch,
  onClose,
  onNew,
  onSelect,
  onView,
}: {
  open: boolean;
  view: View;
  sessions: SessionSummary[];
  activeSessionId: string | null;
  search: string;
  onSearch: (value: string) => void;
  onClose: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onView: (view: View) => void;
}) {
  const navClass = (active: boolean) =>
    `flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
      active
        ? "bg-accent/10 text-foreground"
        : "text-muted hover:bg-surface-raised hover:text-foreground"
    }`;

  return (
    <div className="relative min-h-0 h-full">
      <button
        type="button"
        className={`fixed inset-0 z-30 bg-black/50 transition-opacity lg:hidden ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        aria-label="Chiudi menu"
        onClick={onClose}
      />
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[260px] flex-col border-r border-border bg-[rgba(10,12,17,0.98)] transition-transform lg:static lg:h-full lg:max-h-dvh lg:min-h-0 lg:translate-x-0 lg:overflow-hidden ${
          open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        <div className="flex shrink-0 items-center gap-3 px-5 pb-5 pt-6">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
            <BrainCircuit size={20} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">Harness</div>
            <div className="text-xs text-muted">Control Center</div>
          </div>
          <button
            type="button"
            className="rounded-lg p-1.5 text-muted hover:bg-surface-raised lg:hidden"
            aria-label="Chiudi"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto pb-2">
        <div className="px-4">
          <button
            type="button"
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-soft"
            onClick={onNew}
          >
            <Plus size={17} />
            Nuova sessione
          </button>
        </div>

        <label className="mx-4 mt-4 flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
          <Search size={15} className="shrink-0 text-muted" />
          <input
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-2"
            aria-label="Cerca sessioni"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            placeholder="Cerca sessioni"
          />
        </label>

        <nav className="mt-5 px-4" aria-label="Navigazione principale">
          <p className="mb-2 px-3 text-xs font-medium uppercase tracking-wide text-muted-2">
            Workspace
          </p>
          <div className="space-y-1">
            <button type="button" className={navClass(view === "control")} onClick={() => onView("control")}>
              <Gauge size={17} />
              Control room
            </button>
            <button type="button" className={navClass(view === "traces")} onClick={() => onView("traces")}>
              <Activity size={17} />
              Traces
            </button>
            <button type="button" className={navClass(view === "settings")} onClick={() => onView("settings")}>
              <Settings2 size={17} />
              Impostazioni
            </button>
          </div>

          <p className="mb-2 mt-5 px-3 text-xs font-medium uppercase tracking-wide text-muted-2">
            Loop engineering
          </p>
          <div className="space-y-1">
            <button type="button" className={navClass(view === "triggers")} onClick={() => onView("triggers")}>
              <Timer size={17} />
              Triggers
            </button>
            <button type="button" className={navClass(view === "improve")} onClick={() => onView("improve")}>
              <TrendingUp size={17} />
              Miglioramenti
            </button>
          </div>
        </nav>

        <div className="mt-5 px-4">
          <div className="mb-2 flex items-center justify-between px-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-2">Sessioni</p>
            <span className="rounded-full bg-surface-raised px-2 py-0.5 text-xs text-muted">
              {sessions.length}
            </span>
          </div>
          <div className="space-y-1 pb-2">
            {sessions.length ? (
              sessions.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${
                    item.id === activeSessionId
                      ? "bg-surface-raised text-foreground"
                      : "text-muted hover:bg-surface-raised/60 hover:text-foreground"
                  }`}
                  onClick={() => onSelect(item.id)}
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface text-muted">
                    <Code2 size={15} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{item.title}</div>
                    <div className="text-xs text-muted">{relativeLabel(item.updated_at)}</div>
                  </span>
                  {item.last_status === "running" ? (
                    <span className="h-2 w-2 shrink-0 rounded-full bg-success" />
                  ) : null}
                </button>
              ))
            ) : (
              <p className="px-3 py-4 text-sm text-muted">Nessuna sessione</p>
            )}
          </div>
        </div>
        </div>

        <div className="flex shrink-0 items-center gap-3 border-t border-border px-5 py-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/20 text-sm font-semibold text-accent">
            LA
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">LangChain Harness</div>
            <div className="text-xs text-muted">Local workspace</div>
          </div>
          <CircleCheck size={16} className="shrink-0 text-success" />
        </div>
      </aside>
    </div>
  );
}
