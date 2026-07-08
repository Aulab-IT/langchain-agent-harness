import { Copy, Play, Timer, Trash2, Webhook } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  createTrigger,
  deleteTrigger,
  fireWebhook,
  listTriggers,
  toggleTrigger,
  webhookUrl,
} from "../../api";
import { relativeLabel } from "../../lib/format";
import type { RuntimeStatus, Trigger } from "../../types";

const CRON_HINTS = [
  ["*/5 * * * *", "ogni 5 minuti"],
  ["0 9 * * 1-5", "ogni giorno feriale alle 09:00"],
  ["0 * * * *", "ogni ora"],
];

export function TriggersView({ runtime }: { runtime: RuntimeStatus }) {
  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [kind, setKind] = useState<"cron" | "webhook">("cron");
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [cron, setCron] = useState("*/5 * * * *");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setTriggers(await listTriggers());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Caricamento trigger fallito");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const submit = async () => {
    if (!name.trim() || !goal.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await createTrigger({
        kind,
        name: name.trim(),
        goal_template: goal.trim(),
        cron_expr: kind === "cron" ? cron.trim() : null,
      });
      setName("");
      setGoal("");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Creazione fallita");
    } finally {
      setBusy(false);
    }
  };

  const onToggle = async (trigger: Trigger) => {
    try {
      await toggleTrigger(trigger.id, !trigger.enabled);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Aggiornamento fallito");
    }
  };

  const onDelete = async (trigger: Trigger) => {
    if (!window.confirm(`Eliminare il trigger “${trigger.name}”?`)) return;
    try {
      await deleteTrigger(trigger.id);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Eliminazione fallita");
    }
  };

  const onTest = async (trigger: Trigger) => {
    if (!trigger.token) return;
    try {
      const result = await fireWebhook(trigger.id, trigger.token, { source: "ui-test" });
      setError("");
      window.alert(
        result.run_id ? `Run avviato: ${result.run_id.slice(0, 8)}` : "Trigger saltato (sessione occupata)",
      );
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Test webhook fallito");
    }
  };

  const copy = (text: string) => void navigator.clipboard?.writeText(text);

  return (
    <section className="mx-auto w-full max-w-4xl space-y-4">
      <div className="rounded-xl border border-border bg-surface">
        <div className="flex items-center gap-3 border-b border-border px-6 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-info/20 bg-info/10 text-info">
            <Timer size={18} />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-semibold">Trigger a eventi</h2>
            <p className="text-sm text-muted">Cron e webhook avviano run autonomi</p>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs ${
              runtime.triggers.enabled
                ? "bg-success/10 text-success"
                : "bg-warning/10 text-warning"
            }`}
          >
            {runtime.triggers.enabled
              ? `scheduler attivo · ${runtime.triggers.tick_seconds}s`
              : "scheduler cron spento (HARNESS_ENABLE_TRIGGERS=false)"}
          </span>
        </div>

        <div className="space-y-3 p-6">
          <div className="flex flex-wrap gap-2">
            {(["cron", "webhook"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setKind(option)}
                className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm ${
                  kind === option
                    ? "border-accent bg-accent/10 text-foreground"
                    : "border-border text-muted hover:text-foreground"
                }`}
              >
                {option === "cron" ? <Timer size={14} /> : <Webhook size={14} />}
                {option}
              </button>
            ))}
          </div>
          <input
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
            placeholder="Nome trigger"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <textarea
            className="w-full resize-none rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
            placeholder="Obiettivo (goal template) per il run"
            rows={2}
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
          />
          {kind === "cron" ? (
            <div className="space-y-1">
              <input
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent"
                placeholder="* * * * *"
                value={cron}
                onChange={(event) => setCron(event.target.value)}
              />
              <div className="flex flex-wrap gap-2 text-xs text-muted">
                {CRON_HINTS.map(([expr, label]) => (
                  <button
                    key={expr}
                    type="button"
                    className="rounded border border-border px-2 py-0.5 font-mono hover:text-foreground"
                    onClick={() => setCron(expr)}
                    title={label}
                  >
                    {expr}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted">
              Il webhook riceve un token; il payload dell'evento è trattato come dato non
              attendibile, mai come istruzioni.
            </p>
          )}
          {error ? <p className="text-sm text-danger">{error}</p> : null}
          <button
            type="button"
            onClick={submit}
            disabled={busy || !name.trim() || !goal.trim()}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent hover:bg-accent-soft disabled:opacity-50"
          >
            Crea trigger
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface">
        <div className="border-b border-border px-6 py-4">
          <h3 className="text-sm font-semibold">Trigger configurati ({triggers.length})</h3>
        </div>
        <div className="divide-y divide-border">
          {triggers.length ? (
            triggers.map((trigger) => (
              <div key={trigger.id} className="space-y-2 px-6 py-4">
                <div className="flex items-center gap-3">
                  <span
                    className={`flex h-8 w-8 items-center justify-center rounded-lg border ${
                      trigger.kind === "cron"
                        ? "border-info/20 bg-info/10 text-info"
                        : "border-accent/20 bg-accent/10 text-accent"
                    }`}
                  >
                    {trigger.kind === "cron" ? <Timer size={15} /> : <Webhook size={15} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{trigger.name}</div>
                    <div className="font-mono text-xs text-muted">
                      {trigger.kind === "cron" ? trigger.cron_expr : "webhook"}
                      {trigger.last_fired_at
                        ? ` · ultimo ${relativeLabel(trigger.last_fired_at)}`
                        : " · mai eseguito"}
                    </div>
                  </div>
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
                    <input
                      type="checkbox"
                      checked={trigger.enabled}
                      onChange={() => onToggle(trigger)}
                    />
                    {trigger.enabled ? "attivo" : "disattivo"}
                  </label>
                  {trigger.kind === "webhook" && trigger.token ? (
                    <button
                      type="button"
                      className="rounded-md p-1.5 text-muted hover:bg-surface-raised hover:text-foreground"
                      aria-label="Testa webhook"
                      onClick={() => onTest(trigger)}
                    >
                      <Play size={15} />
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="rounded-md p-1.5 text-muted hover:bg-danger/10 hover:text-danger"
                    aria-label="Elimina trigger"
                    onClick={() => onDelete(trigger)}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
                {trigger.kind === "webhook" && trigger.token ? (
                  <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-raised/40 px-3 py-2">
                    <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono text-xs text-muted">
                      curl -X POST {webhookUrl(trigger.id)} -H &quot;X-Trigger-Token:{" "}
                      {trigger.token}&quot;
                    </code>
                    <button
                      type="button"
                      className="shrink-0 rounded-md p-1.5 text-muted hover:text-foreground"
                      aria-label="Copia comando"
                      onClick={() =>
                        copy(
                          `curl -X POST ${webhookUrl(trigger.id)} -H "X-Trigger-Token: ${trigger.token}"`,
                        )
                      }
                    >
                      <Copy size={14} />
                    </button>
                  </div>
                ) : null}
                <p className="line-clamp-2 text-xs text-muted">{trigger.goal_template}</p>
              </div>
            ))
          ) : (
            <p className="px-6 py-10 text-center text-sm text-muted">
              Nessun trigger. Creane uno per avviare run da cron o webhook.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
