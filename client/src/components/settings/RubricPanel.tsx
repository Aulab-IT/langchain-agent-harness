import { ScrollText, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { getRubric } from "../../api";
import type { Rubric } from "../../types";

export function RubricPanel() {
  const [rubric, setRubric] = useState<Rubric | null>(null);

  useEffect(() => {
    getRubric()
      .then(setRubric)
      .catch(() => undefined);
  }, []);

  if (!rubric) return null;

  return (
    <div className="rounded-xl border border-border bg-surface">
      <div className="flex items-center gap-3 border-b border-border px-6 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-warning/20 bg-warning/10 text-warning">
          <ScrollText size={18} />
        </div>
        <div>
          <h2 className="text-lg font-semibold">Rubrica di verifica</h2>
          <p className="text-sm text-muted">
            Il metro con cui il grader giudica ogni risposta. Congelato: il self-improvement può
            cambiare prompt e limiti, mai la rubrica. {rubric.enabled ? "" : "(grader disattivo)"}
          </p>
        </div>
      </div>

      <div className="grid gap-2 border-b border-border px-6 py-4 sm:grid-cols-3">
        {(
          [
            ["Soglia obiettivo raggiunto", rubric.rubric_threshold, "sotto → l'agente riprova"],
            ["Soglia escalation", rubric.escalation_threshold, "sotto → sale di modello"],
            ["Veto sicurezza", rubric.safety_veto_below, "sotto → voto limitato alla sicurezza"],
          ] as Array<[string, number, string]>
        ).map(([label, value, hint]) => (
          <div key={label} className="rounded-lg border border-border bg-background px-3 py-2">
            <div className="font-mono text-lg">{value}</div>
            <div className="text-xs font-medium">{label}</div>
            <div className="text-[11px] text-muted">{hint}</div>
          </div>
        ))}
      </div>

      <div className="divide-y divide-border">
        {rubric.criteria.map((c) => (
          <div key={c.name} className="flex items-start gap-3 px-6 py-3">
            <span className="mt-0.5 shrink-0 rounded-full border border-border bg-surface-raised px-2 py-0.5 font-mono text-xs">
              {Math.round(c.weight * 100)}%
            </span>
            <div className="min-w-0">
              <div className="text-sm font-medium capitalize">{c.name}</div>
              <div className="text-xs text-muted">{c.description}</div>
            </div>
          </div>
        ))}
      </div>

      <p className="flex items-start gap-2 border-t border-border px-6 py-3 text-xs text-muted">
        <ShieldAlert size={14} className="mt-0.5 shrink-0 text-warning" />
        <span>
          La media è pesata, ma se <strong>sicurezza</strong> scende sotto il veto il voto finale
          viene <strong>limitato</strong> a quel punteggio: un run che distrugge dati non suoi non
          può passare per quanto fosse "completo". Nel trace un veto compare in rosso.
        </span>
      </p>
    </div>
  );
}
