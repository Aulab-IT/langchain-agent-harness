import { CircleCheck, X } from "lucide-react";
import { memo, useState } from "react";
import type { ActivityItem } from "../../types";
import { PanelEmpty } from "../shared/PanelEmpty";

const ActivityRow = memo(function ActivityRow({ item }: { item: ActivityItem }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-raised/30 px-4 py-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface">
        {item.status === "active" ? (
          <span className="h-2.5 w-2.5 rounded-full bg-accent animate-pulse-dot" />
        ) : item.status === "error" ? (
          <X size={14} className="text-danger" />
        ) : (
          <CircleCheck size={14} className="text-success" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{item.name}</div>
        <div className="text-xs text-muted">{item.detail}</div>
      </div>
      <span className="shrink-0 text-xs text-muted">{item.meta}</span>
    </div>
  );
});

export function CapabilitiesPanel({
  skills,
  tools,
}: {
  skills: ActivityItem[];
  tools: ActivityItem[];
}) {
  const [tab, setTab] = useState<"skills" | "tools">("skills");
  const items = tab === "skills" ? skills : tools;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border px-5 py-4">
        <h3 className="text-sm font-semibold">Capabilities</h3>
        <p className="text-xs text-muted">Stato derivato dagli eventi del run</p>
      </div>
      <div className="border-b border-border px-5 py-3">
        <div className="flex rounded-lg border border-border bg-background p-1">
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
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-5">
        {items.length ? (
          items.map((item) => <ActivityRow key={item.id} item={item} />)
        ) : (
          <PanelEmpty>Nessuna capability rilevata.</PanelEmpty>
        )}
      </div>
    </div>
  );
}
