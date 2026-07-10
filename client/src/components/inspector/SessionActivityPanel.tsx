import { CircleCheck, X } from "lucide-react";
import { memo, useState } from "react";
import { formatElapsed, type ActivityEntry } from "../../lib/sessionActivity";
import { PanelEmpty } from "../shared/PanelEmpty";

const EntryRow = memo(function EntryRow({ entry }: { entry: ActivityEntry }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-raised/30 px-4 py-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface">
        {entry.running ? (
          <span className="h-2.5 w-2.5 rounded-full bg-accent animate-pulse-dot" />
        ) : entry.lastStatus === "error" ? (
          <X size={14} className="text-danger" />
        ) : (
          <CircleCheck size={14} className="text-success" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-sm">{entry.name}</div>
        <div className="text-xs text-muted">
          {entry.calls} {entry.calls === 1 ? "invocazione" : "invocazioni"} ·{" "}
          {formatElapsed(entry.totalMs)} totali
        </div>
      </div>
      <span className="shrink-0 text-xs text-muted">
        {entry.running ? "in corso" : entry.lastStatus === "error" ? "errore" : "ok"}
      </span>
    </div>
  );
});

export function SessionActivityPanel({
  skills,
  tools,
}: {
  skills: ActivityEntry[];
  tools: ActivityEntry[];
}) {
  const [tab, setTab] = useState<"tools" | "skills">("tools");
  const entries = tab === "skills" ? skills : tools;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border px-5 py-4">
        <h3 className="text-sm font-semibold">Attività di sessione</h3>
        <p className="text-xs text-muted">Ciò che è stato usato, non ciò che è disponibile</p>
      </div>
      <div className="border-b border-border px-5 py-3">
        <div className="flex rounded-lg border border-border bg-background p-1">
          <button
            type="button"
            className={`flex-1 rounded-md px-3 py-2 text-sm transition-colors ${
              tab === "tools"
                ? "bg-surface-raised font-medium text-foreground"
                : "text-muted hover:text-foreground"
            }`}
            onClick={() => setTab("tools")}
          >
            Tools <span className="ml-1 text-xs text-muted">{tools.length}</span>
          </button>
          <button
            type="button"
            className={`flex-1 rounded-md px-3 py-2 text-sm transition-colors ${
              tab === "skills"
                ? "bg-surface-raised font-medium text-foreground"
                : "text-muted hover:text-foreground"
            }`}
            onClick={() => setTab("skills")}
          >
            Skills <span className="ml-1 text-xs text-muted">{skills.length}</span>
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-5">
        {entries.length ? (
          entries.map((entry) => <EntryRow key={entry.name} entry={entry} />)
        ) : (
          <PanelEmpty>
            {tab === "tools"
              ? "Nessun tool chiamato in questa sessione."
              : "Nessuna skill letta in questa sessione."}
          </PanelEmpty>
        )}
      </div>
    </div>
  );
}
