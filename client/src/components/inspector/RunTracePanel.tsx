import {
  Activity,
  Bot,
  CircleAlert,
  CircleCheck,
  CircleX,
  FileText,
  Gauge,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { relativeLabel, runElapsedSeconds, timeLabel } from "../../lib/format";
import {
  describeCurrentAction,
  describeTraceEvent,
  formatTraceDuration,
  isTraceActionEvent,
  type TraceTone,
} from "../../lib/runTrace";
import type { Run, RunEvent } from "../../types";

function toneClass(tone: TraceTone): string {
  const map: Record<TraceTone, string> = {
    running: "text-accent",
    success: "text-success",
    warning: "text-warning",
    danger: "text-danger",
    muted: "text-muted",
    info: "text-info",
  };
  return map[tone];
}

function iconFor(type: string, tone: TraceTone) {
  if (type.startsWith("tool.")) return Wrench;
  if (type.startsWith("grader.")) return CircleCheck;
  if (type.startsWith("approval.")) return ShieldCheck;
  if (type.startsWith("skill.")) return Sparkles;
  if (type.startsWith("file.")) return FileText;
  if (type.startsWith("usage.")) return Gauge;
  if (type === "agent.started") return Bot;
  if (tone === "danger") return CircleX;
  if (tone === "warning") return CircleAlert;
  return Activity;
}

function rawPayload(payload: Record<string, unknown>): string {
  return JSON.stringify(payload, null, 2);
}

function TraceRow({ event }: { event: RunEvent }) {
  const description = describeTraceEvent(event);
  const Icon = iconFor(event.type, description.tone);
  const payload = rawPayload(event.payload ?? {});

  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2">
      <div className="flex items-start gap-2">
        <Icon size={15} className={`mt-0.5 shrink-0 ${toneClass(description.tone)}`} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-sm font-medium">{description.title}</span>
            <span className="shrink-0 rounded-full border border-border px-2 py-0.5 font-mono text-[11px] text-muted">
              {event.type}
            </span>
          </div>
          {description.detail ? (
            <div className="mt-0.5 truncate font-mono text-xs text-muted">
              {description.detail}
            </div>
          ) : null}
          {payload !== "{}" ? (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs text-muted hover:text-foreground">
                payload evento
              </summary>
              <pre className="mt-1 max-h-44 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-foreground/80">
                {payload}
              </pre>
            </details>
          ) : null}
        </div>
        <span className="shrink-0 font-mono text-xs text-muted-2">
          {timeLabel(event.created_at)}
        </span>
      </div>
    </div>
  );
}

export function RunTracePanel({ run, events }: { run: Run | null; events: RunEvent[] }) {
  const active = Boolean(run && ["queued", "running", "waiting_approval", "waiting_action"].includes(run.status));
  const [now, setNow] = useState(() => Date.now());

  // A run fermo non serve un tick al secondo: aggiornare ogni minuto basta a tenere
  // "N min fa" corretto senza far vedere il numero muoversi in tempo reale.
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), active ? 1000 : 60_000);
    return () => window.clearInterval(timer);
  }, [active]);

  const actionEvents = useMemo(() => events.filter(isTraceActionEvent), [events]);
  const current = useMemo(() => describeCurrentAction(events, run), [events, run]);
  const elapsed = runElapsedSeconds(run) ?? 0;
  const toolCount = actionEvents.filter((event) => event.type === "tool.started").length;
  const failureCount = actionEvents.filter((event) => event.type.endsWith("failed")).length;
  const sinceCurrent = current.startedAt
    ? (now - new Date(current.startedAt).getTime()) / 1000
    : elapsed;
  const CurrentIcon =
    current.tone === "danger" ? CircleX : current.tone === "warning" ? CircleAlert : CircleCheck;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="shrink-0 border-b border-border px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold">Trace live</h3>
            <p className="truncate text-xs text-muted">
              Timeline completa delle azioni del run.
            </p>
          </div>
          <span className="rounded-full border border-border px-2.5 py-1 font-mono text-xs text-muted">
            {run?.status ?? "idle"}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2">
          <div className="rounded-lg border border-border bg-background px-3 py-2">
            <div className="text-xs text-muted">Durata</div>
            <div className="font-mono text-sm">{formatTraceDuration(elapsed)}</div>
          </div>
          <div className="rounded-lg border border-border bg-background px-3 py-2">
            <div className="text-xs text-muted">Tool avviati</div>
            <div className="font-mono text-sm">{toolCount}</div>
          </div>
          <div className="rounded-lg border border-border bg-background px-3 py-2">
            <div className="text-xs text-muted">Errori</div>
            <div className="font-mono text-sm">{failureCount}</div>
          </div>
        </div>
      </div>

      <div className="shrink-0 border-b border-border px-5 py-3">
        <div className="flex items-start gap-2 rounded-lg border border-accent/20 bg-accent/10 px-3 py-2">
          {active ? (
            <span className="mt-1 inline-block h-3.5 w-3.5 shrink-0 rounded-full border-2 border-border border-t-accent animate-spin-slow" />
          ) : (
            <CurrentIcon size={15} className={`mt-0.5 shrink-0 ${toneClass(current.tone)}`} />
          )}
          <div className="min-w-0 flex-1">
            <div className="text-xs text-muted">{active ? "Azione corrente" : "Ultimo stato"}</div>
            <div className="truncate text-sm font-medium">{current.title}</div>
            <div className="truncate text-xs text-muted">
              {current.detail ? `${current.detail} · ` : ""}
              {active
                ? `da ${formatTraceDuration(sinceCurrent)}`
                : current.startedAt
                  ? relativeLabel(current.startedAt)
                  : `${formatTraceDuration(sinceCurrent)} fa`}
            </div>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {actionEvents.length ? (
          <div className="space-y-2">
            {actionEvents.map((event) => (
              <TraceRow key={event.id} event={event} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 py-12 text-center text-muted">
            <Activity size={24} className="text-accent" />
            <strong className="text-sm text-foreground">Trace in avvio</strong>
            <span className="max-w-sm text-sm">
              Quando il run emette eventi, ogni azione appare qui con nome esplicito:
              modello, config, tool, approvazioni, file, grader.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
