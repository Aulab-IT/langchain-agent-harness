import { BrainCircuit, CircleCheck } from "lucide-react";
import { useState } from "react";
import { timeLabel } from "../../lib/format";
import type { RunEvent } from "../../types";

export function ThinkingTrace({ events }: { events: RunEvent[] }) {
  const [open, setOpen] = useState(true);
  const visible = events.slice(-6);

  return (
    <div className="rounded-xl border border-border bg-surface-raised/50">
      <button
        type="button"
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        onClick={() => setOpen((value) => !value)}
      >
        <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
          <BrainCircuit size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">Progress</div>
          <div className="text-xs text-muted">Eventi operativi del run</div>
        </div>
        <span className="text-xs text-muted">{open ? "▾" : "▸"}</span>
      </button>
      {open ? (
        <div className="space-y-2 border-t border-border px-4 py-3">
          {visible.length ? (
            visible.map((event) => (
              <div
                key={event.id}
                className={`flex items-center gap-2 text-sm ${
                  event.type.endsWith("failed") ? "text-danger" : "text-muted"
                }`}
              >
                {event.type.includes("started") ? (
                  <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-border border-t-accent animate-spin-slow" />
                ) : (
                  <CircleCheck size={14} className="shrink-0 text-success" />
                )}
                <span className="font-mono text-xs">{event.type}</span>
                <span className="ml-auto text-xs">{timeLabel(event.created_at)}</span>
              </div>
            ))
          ) : (
            <div className="flex items-center gap-2 text-sm text-muted">
              <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-border border-t-accent animate-spin-slow" />
              Avvio GoalRunner
              <span className="ml-auto text-xs">live</span>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
