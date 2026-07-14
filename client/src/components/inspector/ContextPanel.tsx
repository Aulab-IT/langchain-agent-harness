import { CircleCheck, CircleX, Info, LoaderCircle, Maximize2, Shrink } from "lucide-react";
import { useState } from "react";
import { isTerminalRunStatus } from "../../lib/runStatus";
import type { Run, RunEvent, Usage } from "../../types";
import { ContextModal } from "./ContextModal";

const COMPACTION_RESULTS = new Set([
  "context.compaction.completed",
  "context.compaction.no_work",
  "context.compaction.failed",
]);

function latestEvent(events: RunEvent[], predicate: (event: RunEvent) => boolean): RunEvent | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event && predicate(event)) return event;
  }
  return null;
}

function eventText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function tokenValue(value: unknown): string {
  return typeof value === "number" ? value.toLocaleString("it-IT") : "?";
}

function budgetKindLabel(kind: string): string {
  if (kind === "router") return "Router";
  if (kind === "grader") return "Grader";
  if (kind.startsWith("root:")) return "Agente principale";
  if (kind.startsWith("subagent:")) return kind.slice("subagent:".length);
  return kind;
}

function buildGradient(categories: Usage["context_categories"]): string {
  if (!categories.length) return "conic-gradient(#202631 0 100%)";
  let cursor = 0;
  const stops = categories.map((category) => {
    const start = cursor;
    cursor += category.percent;
    return `${category.color} ${start}% ${cursor}%`;
  });
  return `conic-gradient(${stops.join(",")})`;
}

export function ContextPanel({
  usage,
  contextWindow,
  sessionId,
  run,
  events,
  busy = false,
  onCompact: startCompaction,
}: {
  usage: Usage;
  contextWindow: number;
  sessionId: string;
  run: Run | null;
  events: RunEvent[];
  busy?: boolean;
  onCompact: () => Promise<string>;
}) {
  const contextTokens = usage.context_input_tokens ?? usage.input_tokens;
  const runInputTokens = usage.cumulative_input_tokens ?? usage.input_tokens;
  const runOutputTokens = usage.cumulative_output_tokens ?? usage.output_tokens;
  const runTotalTokens = usage.run_total_tokens ?? runInputTokens + runOutputTokens;
  const runTokenLimit = usage.budget?.limits.max_tokens;
  const runBudgetPercent = runTokenLimit
    ? Math.min(100, Math.round((runTotalTokens / runTokenLimit) * 100))
    : null;
  const projectedTokens = usage.budget?.projected_tokens;
  const budgetBreakdown = Object.entries(usage.budget?.by_call_kind ?? {}).sort(
    (left, right) => right[1].total_tokens - left[1].total_tokens,
  );
  const percent = Math.min(100, Math.round((contextTokens / contextWindow) * 100));
  const gradient = buildGradient(usage.context_categories);
  const [open, setOpen] = useState(false);
  const [compactStarting, setCompactStarting] = useState(false);
  const [compactRunId, setCompactRunId] = useState<string | null>(null);
  const [compactError, setCompactError] = useState<string | null>(null);

  const currentIsCompaction = Boolean(
    run &&
      events.some(
        (event) =>
          event.run_id === run.id &&
          event.type === "run.started" &&
          event.payload.run_kind === "compaction",
      ),
  );
  const trackedRunId =
    compactRunId && (!run || run.id === compactRunId)
      ? compactRunId
      : currentIsCompaction
        ? run?.id ?? null
        : null;
  const compactEvents = trackedRunId
    ? events.filter((event) => event.run_id === trackedRunId)
    : [];
  const resultEvent = latestEvent(compactEvents, (event) => COMPACTION_RESULTS.has(event.type));
  const reductionEvent = latestEvent(
    compactEvents,
    (event) => event.type === "context.compaction.detected",
  );
  const terminalEvent = latestEvent(compactEvents, (event) => {
    if (!event.type.startsWith("run.")) return false;
    return isTerminalRunStatus(event.type.slice(4) as Run["status"]);
  });
  const compacting = compactStarting || Boolean(trackedRunId && !resultEvent && !terminalEvent);

  // Colore della barra secondo la pressione sulla finestra: verde sotto il 70%, ambra fino
  // all'80%, rosso oltre — le stesse soglie con cui il ContextMonitor segnala la pressione.
  const pressure = percent >= 80 ? "high" : percent >= 70 ? "warning" : "ok";
  const pressureColor =
    pressure === "high" ? "text-danger" : pressure === "warning" ? "text-warning" : "text-success";

  async function handleCompactClick() {
    if (busy || compacting) return;
    setCompactStarting(true);
    setCompactRunId(null);
    setCompactError(null);
    try {
      setCompactRunId(await startCompaction());
    } catch (e: unknown) {
      setCompactError(e instanceof Error ? e.message : String(e));
    } finally {
      setCompactStarting(false);
    }
  }

  const feedback = compactError
    ? {
        title: "Compaction non avviata",
        detail: compactError,
        tone: "danger" as const,
        Icon: CircleX,
      }
    : resultEvent?.type === "context.compaction.completed"
      ? {
          title: "Contesto compattato",
          detail: reductionEvent
            ? `${tokenValue(reductionEvent.payload.tokens_before)} → ${tokenValue(reductionEvent.payload.tokens_after)} token; ${tokenValue(reductionEvent.payload.tokens_reclaimed)} liberati.`
            : eventText(resultEvent.payload.message) ?? "Riduzione completata.",
          tone: "success" as const,
          Icon: CircleCheck,
        }
      : resultEvent?.type === "context.compaction.no_work"
        ? {
            title: "Contesto già compatto",
            detail: "Nessuna riduzione necessaria; il task precedente non è stato ripreso.",
            tone: "info" as const,
            Icon: Info,
          }
        : resultEvent?.type === "context.compaction.failed" || terminalEvent
          ? {
              title: "Compaction non riuscita",
              detail:
                eventText(resultEvent?.payload.message) ??
                eventText(terminalEvent?.payload.reason) ??
                eventText(terminalEvent?.payload.error) ??
                "Il run è terminato prima di completare la compaction.",
              tone: "danger" as const,
              Icon: CircleX,
            }
          : compacting
            ? {
                title: "Compaction in corso",
                detail: "Analizzo la storia e riduco il contesto. Il risultato apparirà qui.",
                tone: "running" as const,
                Icon: LoaderCircle,
              }
            : null;

  const feedbackClass =
    feedback?.tone === "success"
      ? "border-success/30 bg-success/5 text-success"
      : feedback?.tone === "danger"
        ? "border-danger/30 bg-danger/5 text-danger"
        : feedback?.tone === "running"
          ? "border-accent/30 bg-accent/5 text-accent"
          : "border-info/30 bg-info/5 text-info";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold">Contesto e budget run</h3>
          <p className="text-xs text-muted">
            {contextTokens ? (
              <span className={pressureColor}>{percent}% finestra modello</span>
            ) : (
              "Nessun dato provider"
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-lg border border-border bg-surface-raised px-2.5 py-1 font-mono text-xs">
            {contextTokens.toLocaleString("it-IT")} / {Math.round(contextWindow / 1_000)}k
          </span>
          <button
            type="button"
            disabled={busy || compacting}
            onClick={handleCompactClick}
            title="Compatta il contesto: riassume la storia più vecchia e libera la finestra"
            className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted hover:border-accent hover:text-foreground disabled:opacity-50"
          >
            <Shrink size={13} />
            {compacting ? "Compatto…" : "Compatta"}
          </button>
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted hover:border-accent hover:text-foreground"
            onClick={() => setOpen(true)}
          >
            <Maximize2 size={13} />
            Dettaglio
          </button>
        </div>
      </div>

      <div className="grid gap-3 px-5 pt-5 md:grid-cols-2">
        <div className="rounded-lg border border-border bg-surface-raised/40 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <strong className="text-sm">Finestra del modello</strong>
              <p className="mt-0.5 text-xs text-muted">Dimensione dell’ultimo prompt.</p>
            </div>
            <span className={`font-mono text-sm font-semibold ${pressureColor}`}>{percent}%</span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-border/60">
            <div
              className={`h-full rounded-full ${
                pressure === "high"
                  ? "bg-danger"
                  : pressure === "warning"
                    ? "bg-warning"
                    : "bg-success"
              }`}
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className="mt-2 font-mono text-xs text-muted">
            {contextTokens.toLocaleString("it-IT")} / {contextWindow.toLocaleString("it-IT")} token
          </div>
        </div>

        <div className="rounded-lg border border-border bg-surface-raised/40 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <strong className="text-sm">Consumo cumulativo run</strong>
              <p className="mt-0.5 text-xs text-muted">Somma di root, router e subagent.</p>
            </div>
            <span
              className={`font-mono text-sm font-semibold ${
                (runBudgetPercent ?? 0) >= 95
                  ? "text-danger"
                  : (runBudgetPercent ?? 0) >= 70
                    ? "text-warning"
                    : "text-info"
              }`}
            >
              {runBudgetPercent == null ? "—" : `${runBudgetPercent}%`}
            </span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-border/60">
            <div
              className={`h-full rounded-full ${
                (runBudgetPercent ?? 0) >= 95
                  ? "bg-danger"
                  : (runBudgetPercent ?? 0) >= 70
                    ? "bg-warning"
                    : "bg-info"
              }`}
              style={{ width: `${runBudgetPercent ?? 0}%` }}
            />
          </div>
          <div className="mt-2 font-mono text-xs text-muted">
            {runTotalTokens.toLocaleString("it-IT")} / {runTokenLimit?.toLocaleString("it-IT") ?? "—"} token
          </div>
          {projectedTokens && runTokenLimit ? (
            <div className="mt-2 rounded border border-warning/25 bg-warning/5 px-2 py-1.5 text-xs text-warning">
              Prossima chiamata: {projectedTokens.toLocaleString("it-IT")} / {runTokenLimit.toLocaleString("it-IT")} proiettati.
            </div>
          ) : null}
        </div>
      </div>

      {budgetBreakdown.length ? (
        <div className="mx-5 mt-3 rounded-lg border border-border bg-background/40 px-4 py-3">
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
            Consumo per componente
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {budgetBreakdown.map(([kind, item]) => (
              <div key={kind} className="flex items-center justify-between gap-3 text-xs">
                <span className="truncate text-muted">{budgetKindLabel(kind)}</span>
                <span className="shrink-0 font-mono">
                  {item.total_tokens.toLocaleString("it-IT")} · {item.model_calls} call
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex flex-col items-center gap-6 p-6 sm:flex-row sm:items-start">
        <button
          type="button"
          onClick={() => setOpen(true)}
          title="Apri il contesto completo"
          className="relative flex h-[140px] w-[140px] shrink-0 items-center justify-center rounded-full p-3 transition-transform hover:scale-[1.03]"
          style={{ background: gradient }}
        >
          <div className="flex h-full w-full flex-col items-center justify-center rounded-full bg-surface text-center">
            <strong className="text-xl font-semibold">
              {contextTokens ? contextTokens.toLocaleString("it-IT") : "—"}
            </strong>
            <span className="text-xs text-muted">token nel prompt</span>
          </div>
        </button>
        <div className="w-full flex-1 space-y-3">
          {usage.context_categories.length ? (
            usage.context_categories.map((category) => (
              <div key={category.name} className="flex items-center gap-3 text-sm">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ background: category.color }}
                />
                <span className="flex-1 text-muted">{category.name}</span>
                <strong className="font-mono text-sm">{category.percent}%</strong>
              </div>
            ))
          ) : (
            <div className="flex items-center gap-3 text-sm text-muted">
              <span className="h-2.5 w-2.5 rounded-full bg-muted-2" />
              In attesa dati
            </div>
          )}
        </div>
      </div>

      {feedback ? (
        <div
          className={`mx-5 mb-3 flex items-start gap-2.5 rounded-lg border px-4 py-3 ${feedbackClass}`}
          role={feedback.tone === "danger" ? "alert" : "status"}
          aria-live="polite"
        >
          <feedback.Icon
            size={16}
            className={`mt-0.5 shrink-0 ${feedback.tone === "running" ? "animate-spin" : ""}`}
          />
          <div className="min-w-0">
            <strong className="block text-sm font-medium">{feedback.title}</strong>
            <span className="mt-0.5 block text-xs leading-relaxed text-foreground/70">
              {feedback.detail}
            </span>
          </div>
        </div>
      ) : null}

      <div className="mx-5 mb-5 rounded-lg border border-border bg-surface-raised/40 px-4 py-3 text-xs leading-relaxed text-muted">
        Operazioni run: {usage.budget?.model_calls ?? 0} / {usage.budget?.limits.max_model_calls ?? 0} call modello; {usage.budget?.subagent_calls ?? 0} / {usage.budget?.limits.max_subagent_calls ?? 0} deleghe uniche.
        {runTokenLimit ? (
          <>
            {" "}
            Input cumulativo: {runInputTokens.toLocaleString("it-IT")}; output cumulativo: {runOutputTokens.toLocaleString("it-IT")}.
          </>
        ) : null}
        {usage.reasoning_tokens ? ` Reasoning: ${usage.reasoning_tokens.toLocaleString("it-IT")} token.` : ""}
        {" "}La compaction riduce prompt futuri, non token già consumati dal run.
        {usage.cost_usd && Number(usage.cost_usd) > 0 ? (
          <>
            {" "}
            Costo stimato del run:{" "}
            <strong className="text-foreground">${Number(usage.cost_usd).toFixed(4)}</strong>.
          </>
        ) : null}
      </div>

      {open ? <ContextModal sessionId={sessionId} onClose={() => setOpen(false)} /> : null}
    </div>
  );
}
