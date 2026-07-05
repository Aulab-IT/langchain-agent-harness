import {
  Activity,
  Bot,
  ChevronRight,
  CircleCheck,
  CircleX,
  Clock3,
  FileText,
  Layers3,
  Play,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useMemo, useState } from "react";
import { timeLabel } from "../../lib/format";
import type { RunEvent } from "../../types";

type ToolStep = {
  kind: "tool";
  key: string;
  name: string;
  at: number;
  elapsedMs: number | null;
  args?: string;
  output?: string;
  status: "completed" | "failed" | "running";
};

type EventStep = {
  kind: "event";
  key: string;
  type: string;
  at: number;
  payload: Record<string, unknown>;
};

type Step = ToolStep | EventStep;

const NOISE = new Set(["assistant.delta", "usage.live", "usage.snapshot"]);

function ms(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

type RunSummary = {
  id: string;
  events: RunEvent[];
  start: number;
  end: number;
  durationMs: number;
  status: "running" | "completed" | "failed" | "cancelled";
  model: string | null;
  inputTokens: number;
  outputTokens: number;
  grader: { passed: boolean; score: number } | null;
  iterations: number | null;
  toolCount: number;
};

function summarize(id: string, events: RunEvent[]): RunSummary {
  const times = events.map((event) => new Date(event.created_at).getTime());
  const start = Math.min(...times);
  const end = Math.max(...times);
  let status: RunSummary["status"] = "running";
  let model: string | null = null;
  let inputTokens = 0;
  let outputTokens = 0;
  let grader: RunSummary["grader"] = null;
  let iterations: number | null = null;
  let durationMs = end - start;
  let toolCount = 0;

  for (const event of events) {
    const p = event.payload ?? {};
    if (event.type === "agent.started" && typeof p.model === "string") model = p.model;
    if (event.type === "run.completed") {
      status = "completed";
      iterations = typeof p.iterations === "number" ? p.iterations : iterations;
      if (typeof p.elapsed_ms === "number") durationMs = p.elapsed_ms;
    }
    if (event.type === "run.failed") status = "failed";
    if (event.type === "run.cancelled") status = "cancelled";
    if (event.type === "grader.completed") {
      grader = { passed: Boolean(p.passed), score: Number(p.score ?? 0) };
    }
    if (event.type === "usage.updated") {
      inputTokens = Number(p.input_tokens ?? inputTokens);
      outputTokens = Number(p.output_tokens ?? outputTokens);
    }
    if (event.type === "usage.snapshot" && !inputTokens) {
      inputTokens = Number(p.input_tokens ?? 0);
      outputTokens = Number(p.output_tokens ?? 0);
    }
    if (event.type === "tool.completed" || event.type === "tool.failed") toolCount += 1;
  }
  return {
    id,
    events,
    start,
    end,
    durationMs,
    status,
    model,
    inputTokens,
    outputTokens,
    grader,
    iterations,
    toolCount,
  };
}

function buildSteps(events: RunEvent[]): Step[] {
  const pending = new Map<string, RunEvent>();
  const steps: Step[] = [];
  for (const event of events) {
    const p = event.payload ?? {};
    const tool = typeof p.tool === "string" ? p.tool : null;
    const at = new Date(event.created_at).getTime();
    if (event.type === "tool.started" && tool) {
      pending.set(tool, event);
      continue;
    }
    if ((event.type === "tool.completed" || event.type === "tool.failed") && tool) {
      const started = pending.get(tool);
      pending.delete(tool);
      steps.push({
        kind: "tool",
        key: `${event.id}`,
        name: tool,
        at: started ? new Date(started.created_at).getTime() : at,
        elapsedMs: ms(p.elapsed_ms),
        args: started ? (started.payload.args as string | undefined) : undefined,
        output: p.output as string | undefined,
        status: event.type === "tool.failed" ? "failed" : "completed",
      });
      continue;
    }
    if (NOISE.has(event.type)) continue;
    steps.push({ kind: "event", key: `${event.id}`, type: event.type, at, payload: p });
  }
  for (const [tool, started] of pending) {
    steps.push({
      kind: "tool",
      key: `run-${started.id}`,
      name: tool,
      at: new Date(started.created_at).getTime(),
      elapsedMs: null,
      args: started.payload.args as string | undefined,
      status: "running",
    });
  }
  return steps.sort((a, b) => a.at - b.at);
}

function eventMeta(type: string) {
  if (type.startsWith("tool.")) return { Icon: Wrench, color: "text-info" };
  if (type.startsWith("grader.")) return { Icon: CircleCheck, color: "text-accent" };
  if (type.startsWith("approval.")) return { Icon: ShieldCheck, color: "text-warning" };
  if (type.startsWith("skill.")) return { Icon: Sparkles, color: "text-accent" };
  if (type.startsWith("file.")) return { Icon: FileText, color: "text-success" };
  if (type === "agent.started") return { Icon: Bot, color: "text-accent" };
  if (type.startsWith("run.")) return { Icon: Play, color: "text-muted" };
  return { Icon: Activity, color: "text-muted" };
}

function StatusBadge({ status }: { status: RunSummary["status"] }) {
  const map: Record<RunSummary["status"], string> = {
    running: "bg-accent/10 text-accent",
    completed: "bg-success/10 text-success",
    failed: "bg-danger/10 text-danger",
    cancelled: "bg-muted-2/20 text-muted",
  };
  return <span className={`rounded-full px-2.5 py-0.5 text-xs ${map[status]}`}>{status}</span>;
}

function Expandable({ label, value }: { label: string; value: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs text-muted hover:text-foreground"
      >
        <ChevronRight size={12} className={open ? "rotate-90 transition-transform" : "transition-transform"} />
        {label}
      </button>
      {open ? (
        <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-foreground/85">
          {value}
        </pre>
      ) : null}
    </div>
  );
}

function ToolRow({ step, runStart, runDuration }: { step: ToolStep; runStart: number; runDuration: number }) {
  const offsetMs = Math.max(0, step.at - runStart);
  const width = runDuration > 0 ? Math.max(2, Math.min(100, ((step.elapsedMs ?? 0) / runDuration) * 100)) : 0;
  const offset = runDuration > 0 ? Math.min(98, (offsetMs / runDuration) * 100) : 0;
  const barColor =
    step.status === "failed" ? "bg-danger" : step.status === "running" ? "bg-accent animate-pulse" : "bg-info";
  return (
    <div className="rounded-lg border border-border bg-surface-raised/30 px-3 py-2">
      <div className="flex items-center gap-2 text-sm">
        <Wrench size={14} className="shrink-0 text-info" />
        <span className="font-mono font-medium">{step.name}</span>
        {step.status === "failed" ? (
          <CircleX size={13} className="text-danger" />
        ) : step.status === "running" ? (
          <span className="h-3 w-3 rounded-full border-2 border-border border-t-accent animate-spin-slow" />
        ) : (
          <CircleCheck size={13} className="text-success" />
        )}
        <span className="ml-auto font-mono text-xs text-muted">
          +{(offsetMs / 1000).toFixed(1)}s
          {step.elapsedMs != null ? ` · ${step.elapsedMs} ms` : " · in corso"}
        </span>
      </div>
      {/* mini waterfall */}
      <div className="mt-1.5 h-1.5 w-full rounded-full bg-surface">
        <div
          className={`h-full rounded-full ${barColor}`}
          style={{ marginLeft: `${offset}%`, width: `${width}%` }}
        />
      </div>
      {step.args ? <Expandable label="argomenti" value={step.args} /> : null}
      {step.output ? <Expandable label="output" value={step.output} /> : null}
    </div>
  );
}

function EventRow({ step }: { step: EventStep }) {
  const { Icon, color } = eventMeta(step.type);
  const keys = Object.keys(step.payload);
  const summary =
    step.type === "grader.completed"
      ? `${step.payload.passed ? "passata" : "non passata"} · ${step.payload.score}`
      : step.type === "agent.started"
        ? String(step.payload.model ?? "")
        : step.type === "approval.auto"
          ? `approvato in autonomia${step.payload.command ? " · " + step.payload.command : ""}`
          : keys.length
            ? JSON.stringify(step.payload)
            : "";
  return (
    <div className="flex items-start gap-2 px-1 py-1.5 text-sm">
      <Icon size={14} className={`mt-0.5 shrink-0 ${color}`} />
      <span className="font-mono text-xs">{step.type}</span>
      {summary ? (
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">· {summary}</span>
      ) : (
        <span className="flex-1" />
      )}
      <span className="shrink-0 font-mono text-xs text-muted-2">{timeLabel(new Date(step.at).toISOString())}</span>
    </div>
  );
}

export function TraceView({ events }: { events: RunEvent[] }) {
  const runs = useMemo(() => {
    const grouped = new Map<string, RunEvent[]>();
    for (const event of events) {
      const list = grouped.get(event.run_id) ?? [];
      list.push(event);
      grouped.set(event.run_id, list);
    }
    return [...grouped.entries()]
      .map(([id, list]) => summarize(id, list))
      .sort((a, b) => b.start - a.start);
  }, [events]);

  const [selected, setSelected] = useState<string | null>(null);
  const run = runs.find((item) => item.id === selected) ?? runs[0];
  const steps = useMemo(() => (run ? buildSteps(run.events) : []), [run]);

  if (!runs.length) {
    return (
      <section className="mx-auto w-full max-w-5xl rounded-xl border border-border bg-surface">
        <div className="flex items-center gap-3 border-b border-border px-6 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-info/20 bg-info/10 text-info">
            <Activity size={18} />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Trace del run</h2>
            <p className="text-sm text-muted">Passo passo di ciò che accade dentro l'agente</p>
          </div>
        </div>
        <div className="flex flex-col items-center gap-2 py-20 text-center">
          <Activity size={28} className="text-info" />
          <strong className="text-base">Nessun trace</strong>
          <span className="text-sm text-muted">Avvia un run nella sessione corrente.</span>
        </div>
      </section>
    );
  }

  return (
    <section className="mx-auto grid w-full max-w-5xl gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
      {/* Elenco run */}
      <aside className="rounded-xl border border-border bg-surface">
        <div className="border-b border-border px-4 py-3 text-xs font-medium uppercase tracking-wide text-muted-2">
          Run ({runs.length})
        </div>
        <div className="max-h-[70vh] divide-y divide-border overflow-y-auto">
          {runs.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setSelected(item.id)}
              className={`flex w-full flex-col gap-1 px-4 py-3 text-left ${
                item.id === run?.id ? "bg-surface-raised" : "hover:bg-surface-raised/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs">{item.id.slice(0, 8)}</span>
                <StatusBadge status={item.status} />
              </div>
              <span className="text-xs text-muted">
                {timeLabel(new Date(item.start).toISOString())} · {(item.durationMs / 1000).toFixed(1)}s
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* Dettaglio run */}
      <div className="min-w-0 space-y-4">
        {run ? (
          <>
            <div className="grid grid-cols-2 gap-2 rounded-xl border border-border bg-surface p-4 sm:grid-cols-4">
              <Metric icon={Clock3} label="Durata" value={`${(run.durationMs / 1000).toFixed(1)}s`} />
              <Metric icon={Bot} label="Modello" value={run.model ?? "—"} />
              <Metric icon={Wrench} label="Tool" value={String(run.toolCount)} />
              <Metric
                icon={Layers3}
                label="Token"
                value={`${run.inputTokens}/${run.outputTokens}`}
              />
              <Metric
                icon={CircleCheck}
                label="Verifica"
                value={run.grader ? `${run.grader.passed ? "ok" : "no"} ${run.grader.score}` : "—"}
              />
              <Metric icon={Play} label="Iterazioni" value={run.iterations != null ? String(run.iterations) : "—"} />
              <div className="col-span-2 flex items-center gap-2 sm:col-span-2">
                <span className="text-xs text-muted">Stato</span>
                <StatusBadge status={run.status} />
              </div>
            </div>

            <div className="rounded-xl border border-border bg-surface">
              <div className="border-b border-border px-4 py-3 text-sm font-medium">
                Timeline · {steps.length} passi
              </div>
              <div className="space-y-2 p-4">
                {steps.map((step) =>
                  step.kind === "tool" ? (
                    <ToolRow key={step.key} step={step} runStart={run.start} runDuration={run.durationMs} />
                  ) : (
                    <EventRow key={step.key} step={step} />
                  ),
                )}
              </div>
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Clock3;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon size={15} className="shrink-0 text-muted" />
      <div className="min-w-0">
        <div className="text-xs text-muted-2">{label}</div>
        <div className="truncate font-mono text-sm">{value}</div>
      </div>
    </div>
  );
}
