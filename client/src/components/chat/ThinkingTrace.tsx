import { BrainCircuit, CircleCheck, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { timeLabel } from "../../lib/format";
import type { Run, RunEvent } from "../../types";

function asText(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

/** Estrae un dettaglio leggibile dal payload: nome tool/skill, comando, modello, esito… */
function eventLabel(event: RunEvent): string | null {
  const p = event.payload ?? {};
  if (event.type === "grader.completed") {
    const passed = p.passed ? "passata" : "non passata";
    const score = asText(p.score);
    return score ? `${passed} · ${score}` : passed;
  }
  return (
    asText(p.tool) ??
    asText(p.skill) ??
    asText(p.command) ??
    asText(p.name) ??
    asText(p.model) ??
    asText(p.action) ??
    asText(p.status) ??
    null
  );
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return minutes ? `${minutes}m ${secs.toString().padStart(2, "0")}s` : `${secs}s`;
}

/** Ultimo tool avviato e non ancora concluso: lo step realmente in corso. */
function activeStep(events: RunEvent[]): RunEvent | null {
  const running = new Map<string, RunEvent>();
  for (const event of events) {
    const tool = typeof event.payload.tool === "string" ? event.payload.tool : null;
    if (!tool) continue;
    if (event.type === "tool.started") running.set(tool, event);
    if (event.type === "tool.completed" || event.type === "tool.failed") running.delete(tool);
  }
  let latest: RunEvent | null = null;
  for (const event of running.values()) {
    if (!latest || event.id > latest.id) latest = event;
  }
  return latest;
}

export function ThinkingTrace({
  events,
  run,
  onStop,
}: {
  events: RunEvent[];
  run: Run | null;
  onStop: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const visible = events.slice(-6);
  const step = useMemo(() => activeStep(events), [events]);
  const lastEvent = events[events.length - 1];

  const runElapsed = run?.started_at ? (now - new Date(run.started_at).getTime()) / 1000 : 0;
  const stepElapsed = step ? (now - new Date(step.created_at).getTime()) / 1000 : 0;
  const sinceLast = lastEvent ? (now - new Date(lastEvent.created_at).getTime()) / 1000 : 0;
  const stepName = step ? eventLabel(step) : null;
  const stale = sinceLast > 20;

  return (
    <div className="rounded-xl border border-border bg-surface-raised/50">
      <div className="flex w-full items-center gap-3 px-4 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
          <BrainCircuit size={16} />
        </div>
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          onClick={() => setOpen((value) => !value)}
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium">
              Progress
              <span className="font-mono text-xs text-muted">{formatDuration(runElapsed)}</span>
            </div>
            <div className="truncate text-xs text-muted">Eventi operativi del run</div>
          </div>
        </button>
        <button
          type="button"
          onClick={onStop}
          className="inline-flex items-center gap-1.5 rounded-lg border border-danger/30 bg-danger/10 px-2.5 py-1 text-xs text-danger hover:bg-danger/20"
        >
          <Square size={10} fill="currentColor" />
          Stop
        </button>
        <button
          type="button"
          className="text-xs text-muted"
          aria-label={open ? "Comprimi" : "Espandi"}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "▾" : "▸"}
        </button>
      </div>

      {/* Step corrente: cosa sta facendo ora e da quanto. */}
      <div className="flex items-center gap-2 border-t border-border px-4 py-2.5 text-sm">
        <span className="inline-block h-3.5 w-3.5 shrink-0 rounded-full border-2 border-border border-t-accent animate-spin-slow" />
        <span className="min-w-0 flex-1 truncate">
          {step ? (
            <>
              In esecuzione: <span className="font-mono text-foreground">{stepName}</span>
            </>
          ) : (
            "Elaborazione del modello…"
          )}
          <span className="text-muted"> · da {formatDuration(stepElapsed || sinceLast)}</span>
        </span>
        {stale ? (
          <span className="shrink-0 rounded-full bg-warning/10 px-2 py-0.5 text-xs text-warning">
            nessun evento da {formatDuration(sinceLast)}
          </span>
        ) : null}
      </div>

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
                {eventLabel(event) ? (
                  <span className="min-w-0 truncate font-mono text-xs text-foreground/80">
                    · {eventLabel(event)}
                  </span>
                ) : null}
                <span className="ml-auto shrink-0 text-xs">{timeLabel(event.created_at)}</span>
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
