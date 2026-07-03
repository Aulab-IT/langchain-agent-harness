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
        className="w-full max-w-lg rounded-xl border border-border bg-surface p-6 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-title"
      >
        <div className="mb-4 flex items-start gap-4">
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
        <pre className="mb-5 overflow-x-auto rounded-lg border border-border bg-background p-4 font-mono text-sm leading-relaxed">
          {String(payload.command || "Comando non disponibile")}
        </pre>
        <div className="flex flex-wrap items-center justify-end gap-3">
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
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent-soft"
            onClick={onApprove}
          >
            <Check size={15} /> Approva
          </button>
        </div>
      </section>
    </div>
  );
}
