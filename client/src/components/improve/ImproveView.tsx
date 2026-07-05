import { Check, FileText, RotateCcw, Sparkles, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  applyImprovement,
  clearOverrides,
  getImprovement,
  listImprovements,
  runImprove,
} from "../../api";
import { relativeLabel } from "../../lib/format";
import type { ImprovementSummary, ImproveResult, RuntimeStatus } from "../../types";
import { MarkdownContent } from "../chat/MarkdownContent";

export function ImproveView({ runtime }: { runtime: RuntimeStatus }) {
  const [items, setItems] = useState<ImprovementSummary[]>([]);
  const [result, setResult] = useState<ImproveResult | null>(null);
  const [content, setContent] = useState<string>("");
  const [apply, setApply] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [overrides, setOverrides] = useState<Record<string, unknown>>(runtime.overrides ?? {});

  const applyProposal = async (name: string) => {
    if (!window.confirm(`Applicare gli override della proposta ${name}?`)) return;
    try {
      const { applied } = await applyImprovement(name);
      setOverrides((current) => ({ ...current, ...applied }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Applicazione fallita");
    }
  };

  const resetOverrides = async () => {
    if (!window.confirm("Rimuovere tutti gli override applicati?")) return;
    try {
      await clearOverrides();
      setOverrides({});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Reset override fallito");
    }
  };

  const refresh = useCallback(async () => {
    try {
      setItems(await listImprovements());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Caricamento proposte fallito");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const generate = async () => {
    if (busy) return;
    if (apply && !window.confirm("Applicare gli override alla config dell'harness dopo la generazione?")) {
      return;
    }
    setBusy(true);
    setError("");
    setContent("");
    try {
      const value = await runImprove(100, apply);
      setResult(value);
      if (apply) setOverrides((current) => ({ ...current, ...value.applied }));
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Generazione proposta fallita");
    } finally {
      setBusy(false);
    }
  };

  const open = async (name: string) => {
    try {
      const detail = await getImprovement(name);
      setContent(detail.content);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Apertura proposta fallita");
    }
  };

  const overrideKeys = Object.keys(overrides);

  return (
    <section className="mx-auto w-full max-w-4xl space-y-4">
      <div className="rounded-xl border border-border bg-surface">
        <div className="flex items-center gap-3 border-b border-border px-6 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
            <TrendingUp size={18} />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-semibold">Miglioramenti (hill climbing)</h2>
            <p className="text-sm text-muted">
              Loop 4 · i trace propongono modifiche alla config. Propose-only + revisione umana.
            </p>
          </div>
        </div>

        <div className="space-y-3 p-6">
          <p className="text-sm text-muted">
            L'agente d'analisi legge gli ultimi 100 run conclusi con grader e tool trace correlati,
            poi propone override sicuri (
            <code className="text-foreground">system_prompt_addendum</code>,{" "}
            <code className="text-foreground">harness_max_tool_calls</code>,{" "}
            <code className="text-foreground">harness_rubric_threshold</code>). La generazione usa il
            modello forte.
          </p>
          <label className="flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={apply} onChange={(event) => setApply(event.target.checked)} />
            Applica gli override dopo la generazione (scrive{" "}
            <code className="text-foreground">state/harness_overrides.toml</code>)
          </label>
          {error ? <p className="text-sm text-danger">{error}</p> : null}
          <button
            type="button"
            onClick={generate}
            disabled={busy || !runtime.configured}
            className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-soft disabled:opacity-50"
          >
            <Sparkles size={16} />
            {busy ? "Analisi in corso…" : "Genera proposta"}
          </button>
          {!runtime.configured ? (
            <p className="text-xs text-warning">OPENAI_API_KEY mancante: generazione disabilitata.</p>
          ) : null}
        </div>

        {overrideKeys.length ? (
          <div className="border-t border-border px-6 py-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-2">
                Override attivi
              </p>
              <button
                type="button"
                onClick={resetOverrides}
                className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted hover:border-danger/40 hover:text-danger"
              >
                <RotateCcw size={12} />
                Azzera
              </button>
            </div>
            <div className="space-y-1">
              {overrideKeys.map((key) => (
                <div key={key} className="flex items-start justify-between gap-3 text-sm">
                  <code className="font-mono text-muted">{key}</code>
                  <code className="max-w-[60%] truncate font-mono text-foreground">
                    {String(overrides[key])}
                  </code>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      {result ? (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-semibold">Ultima proposta · {result.name}</h3>
          <p className="mt-2 text-sm text-muted">{result.summary || "(nessuna sintesi)"}</p>
          {result.findings.length ? (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
              {result.findings.map((finding, index) => (
                <li key={index}>{finding}</li>
              ))}
            </ul>
          ) : null}
          <pre className="mt-3 overflow-x-auto rounded-lg border border-border bg-surface-raised/40 p-3 font-mono text-xs">
            {JSON.stringify(result.overrides, null, 2)}
          </pre>
          {Object.keys(result.applied).length ? (
            <p className="mt-2 text-sm text-success">
              Override applicati: {Object.keys(result.applied).join(", ")}
            </p>
          ) : (
            <p className="mt-2 text-xs text-muted">Propose-only: nessun override applicato.</p>
          )}
        </div>
      ) : null}

      <div className="rounded-xl border border-border bg-surface">
        <div className="border-b border-border px-6 py-4">
          <h3 className="text-sm font-semibold">Proposte salvate ({items.length})</h3>
        </div>
        <div className="divide-y divide-border">
          {items.length ? (
            items.map((item) => (
              <div key={item.name} className="flex items-center gap-3 px-6 py-3">
                <button
                  type="button"
                  onClick={() => open(item.name)}
                  className="flex min-w-0 flex-1 items-center gap-3 text-left"
                >
                  <FileText size={15} className="shrink-0 text-muted" />
                  <span className="min-w-0 flex-1 truncate font-mono text-sm hover:text-foreground">
                    {item.name}
                  </span>
                  <span className="shrink-0 text-xs text-muted">
                    {relativeLabel(item.modified_at)}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => applyProposal(item.name)}
                  className="flex shrink-0 items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted hover:border-success/40 hover:text-success"
                >
                  <Check size={13} />
                  Applica
                </button>
              </div>
            ))
          ) : (
            <p className="px-6 py-10 text-center text-sm text-muted">
              Nessuna proposta. Generane una per iniziare a migliorare l'harness.
            </p>
          )}
        </div>
      </div>

      {content ? (
        <div className="rounded-xl border border-border bg-surface p-6">
          <MarkdownContent content={content} />
        </div>
      ) : null}
    </section>
  );
}
