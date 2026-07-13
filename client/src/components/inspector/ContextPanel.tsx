import { Maximize2, Shrink } from "lucide-react";
import { useState } from "react";
import { compactContext } from "../../api";
import type { Usage } from "../../types";
import { ContextModal } from "./ContextModal";

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
  busy = false,
}: {
  usage: Usage;
  contextWindow: number;
  sessionId: string;
  busy?: boolean;
}) {
  const contextTokens = usage.context_input_tokens ?? usage.input_tokens;
  const runInputTokens = usage.cumulative_input_tokens ?? usage.input_tokens;
  const runOutputTokens = usage.cumulative_output_tokens ?? usage.output_tokens;
  const runTotalTokens = runInputTokens + runOutputTokens;
  const percent = Math.min(100, Math.round((contextTokens / contextWindow) * 100));
  const gradient = buildGradient(usage.context_categories);
  const [open, setOpen] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [compactError, setCompactError] = useState<string | null>(null);

  // Colore della barra secondo la pressione sulla finestra: verde sotto il 70%, ambra fino
  // all'80%, rosso oltre — le stesse soglie con cui il ContextMonitor segnala la pressione.
  const pressure = percent >= 80 ? "high" : percent >= 70 ? "warning" : "ok";
  const pressureColor =
    pressure === "high" ? "text-danger" : pressure === "warning" ? "text-warning" : "text-success";

  async function onCompact() {
    if (busy || compacting) return;
    setCompacting(true);
    setCompactError(null);
    try {
      await compactContext(sessionId);
    } catch (e: unknown) {
      setCompactError(e instanceof Error ? e.message : String(e));
    } finally {
      setCompacting(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold">Contesto ultimo prompt</h3>
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
            onClick={onCompact}
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

      {compactError ? (
        <div className="mx-5 mb-2 rounded-lg border border-danger/30 bg-danger/5 px-4 py-2 text-xs text-danger">
          {compactError}
        </div>
      ) : null}

      <div className="mx-5 mb-5 rounded-lg border border-border bg-surface-raised/40 px-4 py-3 text-xs leading-relaxed text-muted">
        Contesto finale: {contextTokens.toLocaleString("it-IT")} token nell'ultima chiamata.
        Consumo run: {runInputTokens.toLocaleString("it-IT")} input + {runOutputTokens.toLocaleString("it-IT")} output = {runTotalTokens.toLocaleString("it-IT")} token.
        {usage.reasoning_tokens ? ` Reasoning: ${usage.reasoning_tokens.toLocaleString("it-IT")} token.` : ""}
        Breakdown categorie {usage.estimated_context ? "stimato dallo stato graph" : "esatto"}.
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
