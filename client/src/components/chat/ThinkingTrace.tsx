import { BrainCircuit } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { describeCurrentAction, formatClock, formatTraceDuration } from "../../lib/runTrace";
import type { Run, RunEvent } from "../../types";

export function ThinkingTrace({ events, run }: { events: RunEvent[]; run: Run | null }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const current = useMemo(() => describeCurrentAction(events, run), [events, run]);
  const lastEvent = events[events.length - 1];
  const runElapsed = run?.started_at ? (now - new Date(run.started_at).getTime()) / 1000 : 0;
  const currentElapsed = current.startedAt
    ? (now - new Date(current.startedAt).getTime()) / 1000
    : runElapsed;
  const sinceLast = lastEvent ? (now - new Date(lastEvent.created_at).getTime()) / 1000 : 0;
  const stale = sinceLast > 20;
  const toneClass =
    current.tone === "warning"
      ? "border-warning/30 bg-warning/10 text-warning"
      : current.tone === "danger"
        ? "border-danger/30 bg-danger/10 text-danger"
        : "border-accent/20 bg-accent/10 text-accent";

  return (
    <div className="flex items-start gap-3 border-t border-border px-4 py-3 text-sm">
      <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${toneClass}`}>
        <BrainCircuit size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium text-foreground">{current.title}</span>
          {/* Parziale della fase corrente: quanto dura questo singolo passo. */}
          <span className="shrink-0 font-mono text-xs text-muted">
            {formatTraceDuration(currentElapsed || sinceLast)}
          </span>
        </div>
        <div className="truncate text-xs text-muted">
          Apri l'inspector per i dettagli · tab Trace
        </div>
      </div>
      {/* Timer generale: tempo totale del run, sempre visibile e distinto dai parziali di fase. */}
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span
          className="rounded-full border border-border bg-background px-2 py-0.5 font-mono text-xs tabular-nums text-foreground"
          title="Tempo totale del run"
        >
          ⏱ {formatClock(runElapsed)}
        </span>
        {stale ? (
          <span className="rounded-full bg-warning/10 px-2 py-0.5 text-xs text-warning">
            fermo da {formatTraceDuration(sinceLast)}
          </span>
        ) : null}
      </div>
    </div>
  );
}
