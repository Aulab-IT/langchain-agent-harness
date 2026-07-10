import { AlertTriangle, Check, Globe, ShieldCheck, Square } from "lucide-react";

type CommandReview = {
  labels?: string[];
  paths?: string[];
  warnings?: string[];
  parsed?: boolean;
};

function asReview(value: unknown): CommandReview | null {
  if (!value || typeof value !== "object") return null;
  return value as CommandReview;
}

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
  const isNetwork = payload.network === true;
  const review = asReview(payload.review);
  const labels = review?.labels ?? [];
  const paths = review?.paths ?? [];
  const warnings = review?.warnings ?? [];
  const title = isNetwork
    ? "Concedi accesso rete alla sandbox"
    : "Approva comando sandbox";
  const subtitle = isNetwork
    ? `Run ${runId.slice(0, 8)} sospeso. Rete concessa solo per questo comando, poi revocata. Confermata anche in modalità autonoma.`
    : `Run ${runId.slice(0, 8)} sospeso. Comando eseguito senza rete, limiti attivi.`;
  const Icon = isNetwork ? Globe : ShieldCheck;

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
          <div
            className={
              isNetwork
                ? "flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-danger/30 bg-danger/10 text-danger"
                : "flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-warning/30 bg-warning/10 text-warning"
            }
          >
            <Icon size={22} />
          </div>
          <div>
            <h2 id="approval-title" className="text-lg font-semibold">
              {title}
            </h2>
            <p className="mt-1 text-sm text-muted">{subtitle}</p>
          </div>
        </div>
        {isNetwork ? (
          <p className="mx-6 mb-2 rounded-lg border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
            Il container avrà accesso a internet mentre gira questo comando. Consenti solo
            se serve a installare una libreria mancante.
          </p>
        ) : null}
        <div className="mx-6 min-h-0 flex-1 space-y-3 overflow-auto">
          <pre className="overflow-x-auto rounded-lg border border-border bg-background p-4 font-mono text-sm leading-relaxed">
            {String(payload.command || "Comando non disponibile")}
          </pre>

          {labels.length ? (
            <div className="flex flex-wrap gap-1.5">
              {labels.map((label) => (
                <span
                  key={label}
                  className="rounded-full border border-border bg-surface-raised px-2.5 py-1 text-xs text-muted"
                >
                  {label}
                </span>
              ))}
            </div>
          ) : null}

          {paths.length ? (
            <div className="rounded-lg border border-border bg-surface-raised/40 px-4 py-3">
              <div className="text-xs font-medium text-muted">Percorsi citati</div>
              <ul className="mt-1.5 space-y-0.5">
                {paths.map((path) => (
                  <li key={path} className="truncate font-mono text-xs text-foreground">
                    {path}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {warnings.map((warning) => (
            <p
              key={warning}
              className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning"
            >
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <span>{warning}</span>
            </p>
          ))}

          <p className="pb-2 text-xs text-muted">
            Categorie e percorsi vengono riconosciuti da un'analisi statica del testo del
            comando, non da un modello. Un comando può eludere il riconoscimento: leggilo
            comunque. La sandbox resta senza rete, con 512 MB, 1 core, e solo /workspace
            scrivibile.
          </p>
        </div>
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
            className={
              isNetwork
                ? "inline-flex min-h-10 items-center gap-2 rounded-lg bg-danger px-4 text-sm font-semibold text-white hover:opacity-90"
                : "inline-flex min-h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-on-accent hover:bg-accent-soft"
            }
            onClick={onApprove}
          >
            <Check size={15} /> {isNetwork ? "Concedi rete" : "Approva"}
          </button>
        </div>
      </section>
    </div>
  );
}
