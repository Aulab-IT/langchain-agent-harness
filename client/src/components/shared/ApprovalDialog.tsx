import { Check, ShieldCheck, Square } from "lucide-react";

export function ApprovalDialog({
  runId,
  payload,
  onApprove,
  onReject,
  onCancel,
}: {
  runId: string;
  payload: Record<string, unknown>;
  onApprove: () => void;
  onReject: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      role="presentation"
    >
      <section
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-border bg-surface shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-title"
      >
        <div className="flex shrink-0 items-start gap-4 p-6 pb-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-warning/30 bg-warning/10 text-warning">
            <ShieldCheck size={22} />
          </div>
          <div>
            <h2 id="approval-title" className="text-lg font-semibold">
              Approva comando sandbox
            </h2>
            <p className="mt-1 text-sm text-muted">
              Run {runId.slice(0, 8)} sospeso. Comando eseguito senza rete, limiti attivi.
            </p>
          </div>
        </div>
        <pre className="mx-6 min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-background p-4 font-mono text-sm leading-relaxed">
          {String(payload.command || "Comando non disponibile")}
        </pre>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-3 p-6 pt-4">
          <button
            type="button"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-4 text-sm text-muted hover:bg-surface-raised"
            onClick={onCancel}
          >
            <Square size={10} fill="currentColor" /> Annulla run
          </button>
          <button
            type="button"
            className="min-h-10 rounded-lg border border-border px-4 text-sm hover:bg-surface-raised"
            onClick={onReject}
          >
            Rifiuta
          </button>
          <button
            type="button"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-on-accent hover:bg-accent-soft"
            onClick={onApprove}
          >
            <Check size={15} /> Approva
          </button>
        </div>
      </section>
    </div>
  );
}
