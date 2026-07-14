import {
  BrainCircuit,
  Check,
  ChevronDown,
  CircleHelp,
  Gauge,
  RotateCcw,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  WalletCards,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { getRuntimeSettings, updateRuntimeSettings } from "../../api";
import type { RuntimeField } from "../../types";
import { Tooltip } from "../shared/Tooltip";

type GroupKey = "budget" | "context" | "execution" | "quality" | "storage";

type FieldGuide = {
  group: GroupKey;
  explanation: string;
  impact: string;
  recommended: number;
  unit: string;
};

type RuntimeGroup = {
  key: GroupKey;
  title: string;
  description: string;
  icon: LucideIcon;
  defaultOpen: boolean;
};

const GROUPS: RuntimeGroup[] = [
  {
    key: "budget",
    title: "Budget e limiti del run",
    description: "I tetti che fermano la spesa prima della chiamata successiva.",
    icon: WalletCards,
    defaultOpen: true,
  },
  {
    key: "context",
    title: "Contesto e compattazione",
    description: "Quanto testo entra in ogni chiamata e quando viene alleggerito.",
    icon: BrainCircuit,
    defaultOpen: true,
  },
  {
    key: "execution",
    title: "Esecuzione e deleghe",
    description: "Quanti tentativi, tool e subagent può usare un run.",
    icon: Gauge,
    defaultOpen: false,
  },
  {
    key: "quality",
    title: "Qualità ed escalation",
    description: "Quando riprovare e quando passare a un modello più forte.",
    icon: ShieldCheck,
    defaultOpen: false,
  },
  {
    key: "storage",
    title: "Memoria e output",
    description: "Limiti avanzati per dati persistenti e risposte dei tool.",
    icon: Sparkles,
    defaultOpen: false,
  },
];

const FIELD_GUIDES: Record<string, FieldGuide> = {
  max_run_tokens: {
    group: "budget",
    explanation: "Somma input e output di root, router, grader e subagent nello stesso run.",
    impact: "Abbassalo per contenere la spesa; run lunghi possono fermarsi prima.",
    recommended: 500_000,
    unit: "token",
  },
  max_run_cost_usd: {
    group: "budget",
    explanation: "Costo stimato massimo, calcolato con il listino dei modelli configurati.",
    impact: "È la protezione più diretta dalla spesa. Con modelli locali il costo stimato è zero.",
    recommended: 3,
    unit: "USD",
  },
  max_run_seconds: {
    group: "budget",
    explanation: "Durata totale massima, incluse attese di modello, tool e subagent.",
    impact: "Un valore basso evita run bloccati, ma può interrompere lavori con file grandi.",
    recommended: 900,
    unit: "secondi",
  },
  max_model_calls: {
    group: "budget",
    explanation: "Numero cumulativo di chiamate a qualunque modello nel run.",
    impact: "Limita loop e verifiche ripetute. Include router, grader e subagent.",
    recommended: 48,
    unit: "chiamate",
  },
  budget_warning_ratio: {
    group: "budget",
    explanation: "Percentuale del budget alla quale compare un avviso nel trace.",
    impact: "Non ferma il run: segnala solo che uno dei limiti si sta avvicinando.",
    recommended: 0.7,
    unit: "quota 0–1",
  },
  context_window: {
    group: "context",
    explanation: "Finestra di riferimento del modello per il singolo prompt, non consumo totale.",
    impact: "Deve riflettere la capacità reale del modello. Sovrastimarla ritarda la compattazione.",
    recommended: 128_000,
    unit: "token",
  },
  context_warning_ratio: {
    group: "context",
    explanation: "Pressione del prompt alla quale la UI mostra un avviso.",
    impact: "Soglia informativa; non compatta e non ferma il run.",
    recommended: 0.7,
    unit: "quota 0–1",
  },
  context_compaction_ratio: {
    group: "context",
    explanation: "Pressione del prompt che attiva il riassunto automatico della storia.",
    impact: "Più basso risparmia token prima, ma riassume la conversazione più spesso.",
    recommended: 0.8,
    unit: "quota 0–1",
  },
  context_tool_output_tokens: {
    group: "context",
    explanation: "Oltre questa dimensione, un output tool lascia nel prompt solo estratto e link.",
    impact: "Più basso riduce molto il costo dei turni successivi; il contenuto resta su file.",
    recommended: 2_000,
    unit: "token",
  },
  max_continuations: {
    group: "execution",
    explanation: "Tentativi massimi del GoalRunner per completare e verificare l'obiettivo.",
    impact: "Ogni continuazione può generare nuove chiamate. Due bastano per molti task.",
    recommended: 3,
    unit: "tentativi",
  },
  max_tool_calls: {
    group: "execution",
    explanation: "Numero massimo di tool call dell'agente principale nel run.",
    impact: "Riduce loop operativi; valori troppo bassi bloccano ricerche e creazione artefatti.",
    recommended: 56,
    unit: "chiamate",
  },
  max_subagent_calls: {
    group: "execution",
    explanation: "Numero massimo di deleghe avviabili nel run, anche se eseguite in parallelo.",
    impact: "Ogni delega ha contesto e chiamate proprie. Quattro–otto coprono task normali.",
    recommended: 10,
    unit: "deleghe",
  },
  max_subagent_model_calls: {
    group: "execution",
    explanation: "Chiamate modello massime consentite dentro una singola delega.",
    impact: "Ferma un subagent bloccato senza consumare tutto il budget globale.",
    recommended: 10,
    unit: "chiamate",
  },
  max_subagent_tokens: {
    group: "execution",
    explanation: "Input e output cumulativi massimi per ogni singolo subagent.",
    impact: "Isola il costo delle deleghe lunghe; il resto del run conserva budget.",
    recommended: 200_000,
    unit: "token",
  },
  rubric_threshold: {
    group: "quality",
    explanation: "Punteggio minimo del grader per dichiarare raggiunto l'obiettivo.",
    impact: "Più alto aumenta rigore e probabilità di continuazioni aggiuntive.",
    recommended: 0.7,
    unit: "punteggio 0–1",
  },
  escalation_threshold: {
    group: "quality",
    explanation: "Sotto questo punteggio il tentativo passa al gradino modello successivo.",
    impact: "Più alto compra prima modelli costosi; deve restare sotto la soglia obiettivo.",
    recommended: 0.5,
    unit: "punteggio 0–1",
  },
  memory_max_chars: {
    group: "storage",
    explanation: "Dimensione massima della memoria AGENTS.md reinserita in ogni run.",
    impact: "Una memoria grande aumenta stabilmente tutti i prompt futuri.",
    recommended: 32_000,
    unit: "caratteri",
  },
  tool_output_limit: {
    group: "storage",
    explanation: "Caratteri massimi restituiti direttamente da tool e comandi sandbox.",
    impact: "L'eccedenza viene salvata su file. Non è la soglia token del contesto.",
    recommended: 12_000,
    unit: "caratteri",
  },
};

const PRESETS = [
  {
    key: "economy",
    name: "Economico",
    description: "Chat, sintesi e modifiche",
    values: {
      max_run_tokens: 180_000,
      max_run_cost_usd: 1,
      max_run_seconds: 600,
      max_model_calls: 24,
      max_subagent_calls: 4,
      max_subagent_model_calls: 6,
      max_subagent_tokens: 80_000,
      max_continuations: 2,
      max_tool_calls: 30,
      context_tool_output_tokens: 1_500,
    },
  },
  {
    key: "balanced",
    name: "Bilanciato",
    description: "Ricerca e creazione artefatti",
    values: {
      max_run_tokens: 500_000,
      max_run_cost_usd: 3,
      max_run_seconds: 900,
      max_model_calls: 48,
      max_subagent_calls: 10,
      max_subagent_model_calls: 10,
      max_subagent_tokens: 200_000,
      max_continuations: 3,
      max_tool_calls: 56,
      context_tool_output_tokens: 2_000,
    },
  },
  {
    key: "extended",
    name: "Esteso",
    description: "Ricerca, deck e revisione",
    values: {
      max_run_tokens: 900_000,
      max_run_cost_usd: 7,
      max_run_seconds: 1_800,
      max_model_calls: 80,
      max_subagent_calls: 16,
      max_subagent_model_calls: 14,
      max_subagent_tokens: 350_000,
      max_continuations: 5,
      max_tool_calls: 100,
      context_tool_output_tokens: 3_000,
    },
  },
] as const;

const PRESET_IDENTITY_KEYS = [
  "max_run_tokens",
  "max_run_cost_usd",
  "max_run_seconds",
  "max_model_calls",
  "max_subagent_calls",
  "max_subagent_model_calls",
  "max_subagent_tokens",
] as const;

function matchesPreset(
  values: Record<string, string | number>,
  preset: (typeof PRESETS)[number],
): boolean {
  return PRESET_IDENTITY_KEYS.every(
    (key) => Number(values[key]) === Number(preset.values[key]),
  );
}

function displayNumber(value: number): string {
  return Number.isInteger(value) && Math.abs(value) >= 1_000
    ? value.toLocaleString("it-IT")
    : String(value);
}

export function RuntimePanel() {
  const [fields, setFields] = useState<RuntimeField[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [openGroups, setOpenGroups] = useState<Set<GroupKey>>(
    () => new Set(GROUPS.filter((group) => group.defaultOpen).map((group) => group.key)),
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function adopt(next: RuntimeField[]) {
    setFields(next);
    setDraft(Object.fromEntries(next.map((field) => [field.key, String(field.value)])));
  }

  useEffect(() => {
    getRuntimeSettings()
      .then((response) => adopt(response.fields))
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
  }, []);

  function setValue(key: string, value: string) {
    setDraft((previous) => ({ ...previous, [key]: value }));
    setSaved(false);
    setNotice(null);
  }

  function applyPreset(preset: (typeof PRESETS)[number]) {
    setDraft((previous) => {
      const next = { ...previous };
      for (const field of fields) {
        const value = preset.values[field.key as keyof typeof preset.values];
        if (value != null && value >= field.min && value <= field.max) next[field.key] = String(value);
      }
      return next;
    });
    setSaved(false);
    setNotice(`Preset ${preset.name} applicato alla bozza. Salva per renderlo attivo.`);
  }

  function restoreSaved() {
    setDraft(Object.fromEntries(fields.map((field) => [field.key, String(field.value)])));
    setSaved(false);
    setNotice("Modifiche locali annullate.");
  }

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const values: Record<string, number> = {};
      for (const field of fields) {
        const value = Number(draft[field.key]);
        if (Number.isFinite(value) && value !== field.value) values[field.key] = value;
      }
      const updated = await updateRuntimeSettings(values);
      adopt(updated.fields);
      setSaved(true);
      setNotice(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  function toggleGroup(key: GroupKey) {
    setOpenGroups((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const dirty = fields.some((field) => Number(draft[field.key]) !== field.value);
  const changedCount = fields.filter((field) => Number(draft[field.key]) !== field.value).length;
  const savedValues = Object.fromEntries(fields.map((field) => [field.key, field.value]));
  const activePreset = PRESETS.find((preset) => matchesPreset(savedValues, preset));
  const draftPreset = PRESETS.find((preset) => matchesPreset(draft, preset));

  return (
    <div className="rounded-xl border border-border bg-surface">
      <div className="flex items-start gap-3 border-b border-border px-6 py-5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-warning/20 bg-warning/10 text-warning">
          <SlidersHorizontal size={18} />
        </div>
        <div>
          <h2 className="text-lg font-semibold">Budget e comportamento</h2>
          <p className="text-sm text-muted">
            Parti da un preset. Apri i dettagli solo quando serve. Modifiche attive dal run
            successivo, senza riavvio.
          </p>
        </div>
      </div>

      <div className="border-b border-border px-6 py-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium">Profilo di utilizzo</div>
            <div className="text-xs text-muted">
              Attivo: <strong className="text-foreground">{activePreset?.name ?? "Personalizzato"}</strong>
              {dirty ? ` · Bozza: ${draftPreset?.name ?? "Personalizzata"}` : ""}
            </div>
          </div>
          <Tooltip
            content={
              <div className="space-y-1 text-xs text-muted">
                <div className="font-medium text-foreground">Come scegliere</div>
                <p><strong>Economico:</strong> chat, sintesi, modifiche piccole.</p>
                <p><strong>Bilanciato:</strong> uso quotidiano con verifica e deleghe.</p>
                <p><strong>Esteso:</strong> ricerche ampie o presentazioni complesse.</p>
              </div>
            }
          >
            <button type="button" aria-label="Aiuto sui preset" className="text-muted hover:text-foreground">
              <CircleHelp size={16} />
            </button>
          </Tooltip>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {PRESETS.map((preset) => {
            const isActive = activePreset?.key === preset.key;
            const isDraft = dirty && draftPreset?.key === preset.key;
            return (
              <button
                key={preset.key}
                type="button"
                onClick={() => applyPreset(preset)}
                className={`rounded-lg border px-3 py-3 text-left transition hover:border-warning/40 hover:bg-warning/5 ${
                  isDraft
                    ? "border-warning/50 bg-warning/10"
                    : isActive
                      ? "border-success/40 bg-success/5"
                      : "border-border bg-background"
                }`}
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  {preset.name}
                  {isDraft ? (
                    <span className="rounded-full bg-warning/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-warning">
                      bozza
                    </span>
                  ) : isActive ? (
                    <span className="rounded-full bg-success/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-success">
                      attivo
                    </span>
                  ) : preset.key === "balanced" ? (
                    <span className="rounded-full bg-warning/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-warning">
                      consigliato
                    </span>
                  ) : null}
                </span>
                <span className="mt-0.5 block text-xs text-muted">{preset.description}</span>
                <span className="mt-2 block font-mono text-[11px] text-muted">
                  {displayNumber(preset.values.max_run_tokens)} token · ${preset.values.max_run_cost_usd}
                </span>
              </button>
            );
          })}
        </div>
        <div className="mt-3 rounded-lg border border-info/20 bg-info/5 px-3 py-2 text-xs text-muted">
          Suggerimento: per controllare la spesa modifica prima <strong className="text-foreground">Token max run</strong> e <strong className="text-foreground">Costo max run</strong>. Gli altri valori possono restare su Bilanciato.
        </div>
      </div>

      <div className="divide-y divide-border">
        {GROUPS.map((group) => {
          const groupFields = fields.filter(
            (field) => (FIELD_GUIDES[field.key]?.group ?? "storage") === group.key,
          );
          if (!groupFields.length) return null;
          const open = openGroups.has(group.key);
          const Icon = group.icon;
          return (
            <section key={group.key}>
              <button
                type="button"
                onClick={() => toggleGroup(group.key)}
                aria-expanded={open}
                className="flex w-full items-center gap-3 px-6 py-4 text-left transition hover:bg-surface-raised/30"
              >
                <Icon size={16} className="shrink-0 text-warning" />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{group.title}</span>
                  <span className="block text-xs text-muted">{group.description}</span>
                </span>
                <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-muted">
                  {groupFields.length}
                </span>
                <ChevronDown size={16} className={`text-muted transition ${open ? "rotate-180" : ""}`} />
              </button>

              {open ? (
                <div className="grid gap-3 bg-background/30 px-6 pb-5 pt-1 sm:grid-cols-2">
                  {groupFields.map((field) => {
                    const guide = FIELD_GUIDES[field.key];
                    const changed = Number(draft[field.key]) !== field.value;
                    return (
                      <div
                        key={field.key}
                        className={`rounded-lg border p-3 transition ${
                          changed ? "border-warning/40 bg-warning/5" : "border-border bg-background"
                        }`}
                      >
                        <div className="mb-2 flex items-start justify-between gap-2">
                          <span>
                            <label
                              htmlFor={`runtime-${field.key}`}
                              className="block text-sm font-medium"
                            >
                              {field.label}
                            </label>
                            <span className="block text-[11px] text-muted">{field.hint}</span>
                          </span>
                          <Tooltip
                            className="shrink-0"
                            content={
                              <div className="space-y-2 text-xs text-muted">
                                <div className="font-medium text-foreground">{field.label}</div>
                                <p>{guide?.explanation ?? field.hint}</p>
                                {guide ? <p>{guide.impact}</p> : null}
                                <div className="border-t border-border pt-2">
                                  Consigliato: <strong className="font-mono text-foreground">{guide ? displayNumber(guide.recommended) : "—"}</strong>{guide?.unit ? ` ${guide.unit}` : ""}
                                  <br />Range ammesso: <span className="font-mono">{displayNumber(field.min)}–{displayNumber(field.max)}</span>
                                </div>
                              </div>
                            }
                          >
                            <button
                              type="button"
                              aria-label={`Spiegazione di ${field.label}`}
                              className="text-muted hover:text-foreground"
                            >
                              <CircleHelp size={15} />
                            </button>
                          </Tooltip>
                        </div>
                        <span className="relative block">
                          <input
                            id={`runtime-${field.key}`}
                            type="number"
                            step={field.is_int ? 1 : 0.05}
                            min={field.min}
                            max={field.max}
                            value={draft[field.key] ?? ""}
                            onChange={(event) => setValue(field.key, event.target.value)}
                            className="w-full rounded-lg border border-border bg-surface px-3 py-2 pr-24 font-mono text-sm outline-none focus:border-warning/50"
                          />
                          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[10px] text-muted">
                            {guide?.unit ?? "valore"}
                          </span>
                        </span>
                        <span className="mt-2 flex items-center justify-between text-[10px] text-muted">
                          <span>Consigliato: {guide ? displayNumber(guide.recommended) : "—"}</span>
                          {changed ? <span className="font-medium text-warning">Modificato</span> : null}
                        </span>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </section>
          );
        })}
      </div>

      <div className="flex flex-col gap-3 border-t border-border px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-h-5 text-sm">
          {error ? (
            <span className="text-danger">{error}</span>
          ) : saved ? (
            <span className="inline-flex items-center gap-1.5 text-success"><Check size={14} /> Salvato. Attivo dal prossimo run.</span>
          ) : notice ? (
            <span className="text-info">{notice}</span>
          ) : dirty ? (
            <span className="text-warning">{changedCount} {changedCount === 1 ? "modifica non salvata" : "modifiche non salvate"}</span>
          ) : (
            <span className="text-muted">Nessuna modifica.</span>
          )}
        </div>
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={restoreSaved}
            disabled={!dirty || saving}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted transition hover:text-foreground disabled:opacity-40"
          >
            <RotateCcw size={14} /> Annulla
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving || !dirty}
            className="inline-flex items-center gap-2 rounded-lg border border-warning/20 bg-warning/10 px-4 py-2 text-sm font-medium text-warning transition hover:bg-warning/20 disabled:opacity-50"
          >
            <Save size={15} /> {saving ? "Salvataggio…" : "Salva modifiche"}
          </button>
        </div>
      </div>
    </div>
  );
}
