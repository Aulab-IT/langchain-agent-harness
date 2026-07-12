import { DollarSign, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { getCosts } from "../../api";
import type { CostSummary } from "../../types";

function money(value: string): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "$0";
  if (n < 0.0001) return "<$0.0001";
  return `$${n.toFixed(4)}`;
}

export function CostsPanel() {
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(false);

  function refresh() {
    setLoading(true);
    getCosts()
      .then(setCosts)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  return (
    <div className="rounded-xl border border-border bg-surface">
      <div className="flex items-center gap-3 border-b border-border px-6 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-warning/20 bg-warning/10 text-warning">
          <DollarSign size={18} />
        </div>
        <div className="flex-1">
          <h2 className="text-lg font-semibold">Costi</h2>
          <p className="text-sm text-muted">
            Stima in dollari dal listino attivo, a granularità di run. I provider locali contano 0.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted transition hover:text-foreground disabled:opacity-50"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Aggiorna
        </button>
      </div>

      <div className="border-b border-border px-6 py-5">
        <div className="text-xs text-muted">Totale finora</div>
        <div className="font-mono text-2xl font-semibold">{costs ? money(costs.total_usd) : "—"}</div>
      </div>

      {costs && costs.sessions.length ? (
        <div className="px-6 py-4">
          <div className="mb-2 text-xs font-medium text-muted">Per sessione</div>
          <div className="flex flex-col gap-1">
            {costs.sessions.slice(0, 8).map((s) => (
              <div
                key={s.session_id}
                className="flex items-center justify-between gap-2 text-sm"
              >
                <span className="truncate text-muted" title={s.title}>
                  {s.title}
                  <span className="ml-1 text-[11px]">· {s.runs} run</span>
                </span>
                <span className="shrink-0 font-mono">{money(s.cost_usd)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="px-6 py-6 text-center text-xs text-muted">
          Ancora nessun costo registrato. Lancia un run con un modello cloud.
        </p>
      )}
    </div>
  );
}
