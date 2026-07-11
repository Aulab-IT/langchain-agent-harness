import { KeyRound, Layers, RefreshCw, Save, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { getProviderModels, getProviderSettings, updateProviderSettings } from "../../api";
import type {
  ModelTier,
  ProviderModels,
  ProviderName,
  ProviderSettings,
  RuntimeStatus,
} from "../../types";

type TierRow = { tier: ModelTier; provider: ProviderName; model: string };

const LOCAL_PROVIDERS: ProviderName[] = ["ollama", "mlx"];

export function SettingsView({
  runtime,
  onSaved,
}: {
  runtime: RuntimeStatus;
  onSaved: () => void;
}) {
  const [config, setConfig] = useState<ProviderSettings | null>(null);
  const [tiers, setTiers] = useState<TierRow[]>([]);
  const [openaiKey, setOpenaiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [local, setLocal] = useState<Record<string, ProviderModels>>({});
  const [probing, setProbing] = useState(false);

  function adopt(next: ProviderSettings) {
    setConfig(next);
    setTiers(next.tiers.map((t) => ({ tier: t.tier, provider: t.provider, model: t.model })));
  }

  function probeLocal() {
    setProbing(true);
    Promise.all(
      LOCAL_PROVIDERS.map((p) =>
        getProviderModels(p)
          .then((r) => [p, r] as const)
          .catch(() => [p, { running: false, models: [] }] as const),
      ),
    )
      .then((entries) => setLocal(Object.fromEntries(entries)))
      .finally(() => setProbing(false));
  }

  useEffect(() => {
    getProviderSettings()
      .then(adopt)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    probeLocal();
  }, []);

  function modelOptions(provider: ProviderName): string[] {
    const live = local[provider]?.models ?? [];
    if (live.length) return live;
    return config?.suggested_models[provider] ?? [];
  }

  function changeProvider(tier: ModelTier, provider: ProviderName) {
    setSaved(false);
    const options = modelOptions(provider);
    setTiers((prev) =>
      prev.map((row) =>
        row.tier === tier ? { ...row, provider, model: options[0] ?? "" } : row,
      ),
    );
  }

  function changeModel(tier: ModelTier, model: string) {
    setSaved(false);
    setTiers((prev) => prev.map((row) => (row.tier === tier ? { ...row, model } : row)));
  }

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const body: { openai_api_key?: string; anthropic_api_key?: string; tiers: TierRow[] } = {
        tiers,
      };
      if (openaiKey) body.openai_api_key = openaiKey;
      if (anthropicKey) body.anthropic_api_key = anthropicKey;
      const updated = await updateProviderSettings(body);
      adopt(updated);
      setOpenaiKey("");
      setAnthropicKey("");
      setSaved(true);
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const keyInput = (value: string, onChange: (v: string) => void, configured: boolean) => (
    <input
      type="password"
      value={value}
      autoComplete="off"
      onChange={(e) => {
        onChange(e.target.value);
        setSaved(false);
      }}
      placeholder={configured ? "•••• configurata — digita per sostituire" : "non configurata"}
      className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-warning/40"
    />
  );

  const openaiInfo = config?.providers.find((p) => p.name === "openai");
  const anthropicInfo = config?.providers.find((p) => p.name === "anthropic");

  return (
    <section className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <div className="rounded-xl border border-border bg-surface">
        <div className="flex items-center gap-3 border-b border-border px-6 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-warning/20 bg-warning/10 text-warning">
            <Settings2 size={18} />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Provider e modelli</h2>
            <p className="text-sm text-muted">
              Chiavi API e assegnazione provider/modello ai tre gradini. Valgono dal run
              successivo, senza riavviare.
            </p>
          </div>
        </div>

        <div className="border-b border-border px-6 py-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium">
            <KeyRound size={15} className="text-muted" /> Chiavi API
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-sm text-muted">OpenAI</span>
              {keyInput(openaiKey, setOpenaiKey, openaiInfo?.key_configured ?? false)}
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-sm text-muted">Claude (Anthropic)</span>
              {keyInput(anthropicKey, setAnthropicKey, anthropicInfo?.key_configured ?? false)}
            </label>
          </div>
          <p className="mt-2 text-xs text-muted">
            Le chiavi non vengono mai rimostrate: il campo vuoto lascia invariata quella salvata.
          </p>
        </div>

        <div className="px-6 py-5">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Layers size={15} className="text-muted" /> Gradini della scala
            </div>
            <button
              type="button"
              onClick={probeLocal}
              disabled={probing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted transition hover:text-foreground disabled:opacity-50"
              title="Rileva i modelli dei provider locali (ollama list)"
            >
              <RefreshCw size={13} className={probing ? "animate-spin" : ""} /> Rileva locali
            </button>
          </div>
          <div className="flex flex-col gap-3">
            {tiers.map((row) => {
              const isLocal = LOCAL_PROVIDERS.includes(row.provider);
              const probe = local[row.provider];
              return (
                <div key={row.tier} className="grid items-start gap-3 sm:grid-cols-[80px_1fr_1fr]">
                  <span className="pt-2 text-sm font-medium capitalize">{row.tier}</span>
                  <select
                    value={row.provider}
                    onChange={(e) => changeProvider(row.tier, e.target.value as ProviderName)}
                    className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-warning/40"
                  >
                    {config?.providers.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                  <div className="flex flex-col gap-1">
                    {isLocal && probe?.running && probe.models.length ? (
                      <select
                        value={row.model}
                        onChange={(e) => changeModel(row.tier, e.target.value)}
                        className="rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-warning/40"
                      >
                        {!probe.models.includes(row.model) && row.model ? (
                          <option value={row.model}>{row.model} (non installato)</option>
                        ) : null}
                        {probe.models.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        list={`models-${row.tier}`}
                        value={row.model}
                        onChange={(e) => changeModel(row.tier, e.target.value)}
                        placeholder="nome modello"
                        className="rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-warning/40"
                      />
                    )}
                    <datalist id={`models-${row.tier}`}>
                      {modelOptions(row.provider).map((m) => (
                        <option key={m} value={m} />
                      ))}
                    </datalist>
                    {isLocal ? (
                      <span className="text-xs text-muted">
                        {probe?.running
                          ? `in esecuzione · ${probe.models.length} modelli`
                          : "non in esecuzione — avvia con `ollama serve`"}
                      </span>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-6 py-4">
          <div className="text-sm">
            {error ? (
              <span className="text-danger">{error}</span>
            ) : saved ? (
              <span className="text-success">Salvato. Attivo dal prossimo run.</span>
            ) : (
              <span className="text-muted">
                Un gradino su provider cloud richiede la relativa chiave.
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={save}
            disabled={saving || !config}
            className="inline-flex items-center gap-2 rounded-lg border border-warning/20 bg-warning/10 px-4 py-2 text-sm font-medium text-warning transition hover:bg-warning/20 disabled:opacity-50"
          >
            <Save size={15} /> {saving ? "Salvataggio…" : "Salva"}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface">
        <div className="border-b border-border px-6 py-4 text-sm font-medium">Runtime</div>
        <div className="divide-y divide-border">
          {(
            [
              ["Backend", runtime.backend],
              ["Finestra contesto", `${runtime.context_window.toLocaleString("it-IT")} token`],
              ["Sandbox image", runtime.sandbox.image],
              [
                "Approvazione sandbox",
                runtime.sandbox.approval_required ? "richiesta" : "disabilitata",
              ],
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
            ] as Array<[string, string]>
          ).map(([label, value]) => (
            <div
              key={label}
              className="flex flex-col gap-1 px-6 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <span className="text-sm text-muted">{label}</span>
              <code className="font-mono text-sm">{value}</code>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
