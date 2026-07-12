import { Save, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { getRuntimeSettings, updateRuntimeSettings } from "../../api";
import type { RuntimeField } from "../../types";

export function RuntimePanel() {
  const [fields, setFields] = useState<RuntimeField[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function adopt(next: RuntimeField[]) {
    setFields(next);
    setDraft(Object.fromEntries(next.map((f) => [f.key, String(f.value)])));
  }

  useEffect(() => {
    getRuntimeSettings()
      .then((r) => adopt(r.fields))
      .catch(() => undefined);
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const values: Record<string, number> = {};
      for (const f of fields) {
        const n = Number(draft[f.key]);
        if (Number.isFinite(n) && n !== f.value) values[f.key] = n;
      }
      const updated = await updateRuntimeSettings(values);
      adopt(updated.fields);
      setSaved(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const dirty = fields.some((f) => Number(draft[f.key]) !== f.value);

  return (
    <div className="rounded-xl border border-border bg-surface">
      <div className="flex items-center gap-3 border-b border-border px-6 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-warning/20 bg-warning/10 text-warning">
          <SlidersHorizontal size={18} />
        </div>
        <div>
          <h2 className="text-lg font-semibold">Parametri runtime</h2>
          <p className="text-sm text-muted">
            Soglie e limiti del comportamento dell'agente. Prima solo da <code>.env</code> con
            riavvio; qui valgono dal run successivo. Fuori range vengono rifiutati.
          </p>
        </div>
      </div>

      <div className="grid gap-4 px-6 py-5 sm:grid-cols-2">
        {fields.map((f) => (
          <label key={f.key} className="flex flex-col gap-1">
            <span className="flex items-baseline justify-between text-sm">
              <span>{f.label}</span>
              <span className="font-mono text-[11px] text-muted">
                {f.min}–{f.max}
              </span>
            </span>
            <input
              type="number"
              step={f.is_int ? 1 : 0.05}
              min={f.min}
              max={f.max}
              value={draft[f.key] ?? ""}
              onChange={(e) => {
                setDraft((prev) => ({ ...prev, [f.key]: e.target.value }));
                setSaved(false);
              }}
              className="rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-warning/40"
            />
            <span className="text-[11px] text-muted">{f.hint}</span>
          </label>
        ))}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-border px-6 py-4">
        <div className="text-sm">
          {error ? (
            <span className="text-danger">{error}</span>
          ) : saved ? (
            <span className="text-success">Salvato. Attivo dal prossimo run.</span>
          ) : (
            <span className="text-muted">I valori si applicano dal run successivo.</span>
          )}
        </div>
        <button
          type="button"
          onClick={save}
          disabled={saving || !dirty}
          className="inline-flex items-center gap-2 rounded-lg border border-warning/20 bg-warning/10 px-4 py-2 text-sm font-medium text-warning transition hover:bg-warning/20 disabled:opacity-50"
        >
          <Save size={15} /> {saving ? "Salvataggio…" : "Salva"}
        </button>
      </div>
    </div>
  );
}
