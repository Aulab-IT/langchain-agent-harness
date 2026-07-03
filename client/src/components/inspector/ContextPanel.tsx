import type { Usage } from "../../types";

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
}: {
  usage: Usage;
  contextWindow: number;
}) {
  const percent = Math.min(100, Math.round((usage.input_tokens / contextWindow) * 100));
  const gradient = buildGradient(usage.context_categories);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold">Contesto ultimo run</h3>
          <p className="text-xs text-muted">
            {usage.total_tokens ? `${percent}% finestra modello` : "Nessun dato provider"}
          </p>
        </div>
        <span className="rounded-lg border border-border bg-surface-raised px-2.5 py-1 font-mono text-xs">
          {usage.input_tokens} / {Math.round(contextWindow / 1_000)}k
        </span>
      </div>

      <div className="flex flex-col items-center gap-6 p-6 sm:flex-row sm:items-start">
        <div
          className="relative flex h-[140px] w-[140px] shrink-0 items-center justify-center rounded-full p-3"
          style={{ background: gradient }}
        >
          <div className="flex h-full w-full flex-col items-center justify-center rounded-full bg-surface text-center">
            <strong className="text-xl font-semibold">{usage.total_tokens || "—"}</strong>
            <span className="text-xs text-muted">token totali</span>
          </div>
        </div>
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

      <div className="mx-5 mb-5 rounded-lg border border-border bg-surface-raised/40 px-4 py-3 text-xs leading-relaxed text-muted">
        Totale provider esatto: {usage.input_tokens} input + {usage.output_tokens} output.
        Breakdown categorie {usage.estimated_context ? "stimato dallo stato graph" : "esatto"}.
      </div>
    </div>
  );
}
