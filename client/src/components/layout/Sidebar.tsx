import {
  Activity,
  BrainCircuit,
  Bot,
  CircleCheck,
  Gauge,
  Settings2,
  Sparkles,
  Timer,
  TrendingUp,
  Wrench,
  X,
} from "lucide-react";
import type { View } from "../../lib/constants";
import type { SessionSummary } from "../../types";
import { SessionSwitcher } from "./SessionSwitcher";

export function Sidebar({
  open,
  view,
  sessions,
  activeSessionId,
  activeTitle,
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
  activeTitle: string | null;
  search: string;
  onSearch: (value: string) => void;
  onClose: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onView: (view: View) => void;
}) {
  const navClass = (active: boolean) =>
    `flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
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
        <div className="flex shrink-0 items-center gap-3 px-5 pb-3 pt-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
            <BrainCircuit size={20} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">Agent Studio</div>
            <div className="text-xs text-muted">Console locale</div>
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

        <div className="shrink-0 px-4 pb-3">
          <SessionSwitcher
            sessions={sessions}
            activeSessionId={activeSessionId}
            activeTitle={activeTitle}
            search={search}
            onSearch={onSearch}
            onSelect={onSelect}
            onNew={onNew}
          />
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <nav className="px-4 pb-2" aria-label="Navigazione principale">
            <p className="mb-2 px-3 text-xs font-medium uppercase tracking-wide text-muted-2">
              Sessione
            </p>
            <div className="space-y-1">
              <button type="button" className={navClass(view === "control")} onClick={() => onView("control")}>
                <Gauge size={17} />
                Agente
              </button>
              <button type="button" className={navClass(view === "traces")} onClick={() => onView("traces")}>
                <Activity size={17} />
                Cronologia
              </button>
            </div>

            <p className="mb-2 mt-4 px-3 text-xs font-medium uppercase tracking-wide text-muted-2">
              Generale
            </p>
            <div className="space-y-1">
              <button type="button" className={navClass(view === "skills")} onClick={() => onView("skills")}>
                <Sparkles size={17} />
                Skills
              </button>
              <button type="button" className={navClass(view === "subagents")} onClick={() => onView("subagents")}>
                <Bot size={17} />
                Subagent
              </button>
              <button type="button" className={navClass(view === "tools")} onClick={() => onView("tools")}>
                <Wrench size={17} />
                Tools
              </button>
              <button type="button" className={navClass(view === "triggers")} onClick={() => onView("triggers")}>
                <Timer size={17} />
                Trigger
              </button>
              <button type="button" className={navClass(view === "improve")} onClick={() => onView("improve")}>
                <TrendingUp size={17} />
                Miglioramenti
              </button>
              <button type="button" className={navClass(view === "settings")} onClick={() => onView("settings")}>
                <Settings2 size={17} />
                Impostazioni
              </button>
            </div>
          </nav>

          <div className="mt-auto flex shrink-0 items-center gap-3 border-t border-border px-5 py-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/20 text-sm font-semibold text-accent">
              AS
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">Agent Studio</div>
              <div className="text-xs text-muted">Local workspace</div>
            </div>
            <CircleCheck size={16} className="shrink-0 text-success" />
          </div>
        </div>
      </aside>
    </div>
  );
}
