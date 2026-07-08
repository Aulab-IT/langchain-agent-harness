import { Settings2 } from "lucide-react";
import type { RuntimeStatus } from "../../types";

export function SettingsView({ runtime }: { runtime: RuntimeStatus }) {
  const rows = [
    ["Backend", runtime.backend],
    ["Configurazione", runtime.configured ? "completa" : "OPENAI_API_KEY mancante"],
    ["Modello default", runtime.model],
    ["Modello strong", runtime.strong_model],
    ["Finestra contesto", `${runtime.context_window.toLocaleString("it-IT")} token`],
    ["Sandbox image", runtime.sandbox.image],
    ["Approvazione sandbox", runtime.sandbox.approval_required ? "richiesta" : "disabilitata"],
    ["Rete sandbox", runtime.sandbox.network],
    [
      "Verifica rubric",
      runtime.verification.enabled
        ? `attiva · soglia ${runtime.verification.threshold}`
        : "disattiva",
    ],
    [
      "Trigger scheduler",
      runtime.triggers.enabled ? `attivo · ${runtime.triggers.tick_seconds}s` : "spento",
    ],
  ];

  return (
    <section className="mx-auto w-full max-w-4xl rounded-xl border border-border bg-surface">
      <div className="border-b border-border px-6 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-warning/20 bg-warning/10 text-warning">
            <Settings2 size={18} />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Impostazioni runtime</h2>
            <p className="text-sm text-muted">Valori reali letti dal backend locale</p>
          </div>
        </div>
      </div>
      <div className="divide-y divide-border">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex flex-col gap-1 px-6 py-4 sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="text-sm text-muted">{label}</span>
            <code className="font-mono text-sm">{value}</code>
          </div>
        ))}
      </div>
      <p className="border-t border-border px-6 py-4 text-sm text-muted">
        Configurazione modificabile tramite file <code className="text-foreground">.env</code>;
        riavvia API dopo modifica.
      </p>
    </section>
  );
}
