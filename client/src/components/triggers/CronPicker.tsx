import { CalendarClock } from "lucide-react";
import { useEffect, useState } from "react";
import { previewCron } from "../../api";
import { browserZone } from "../../lib/timezone";
import type { CronPreview } from "../../types";

const PRESETS: Array<{ label: string; expr: string }> = [
  { label: "Ogni 15 minuti", expr: "*/15 * * * *" },
  { label: "Ogni ora", expr: "0 * * * *" },
  { label: "Ogni giorno alle 09:00", expr: "0 9 * * *" },
  { label: "Ogni giorno feriale alle 09:00", expr: "0 9 * * 1-5" },
  { label: "Ogni lunedì alle 08:30", expr: "30 8 * * 1" },
  { label: "Il primo del mese a mezzanotte", expr: "0 0 1 * *" },
];

// Il fuso del browser è quello che l'utente si aspetta; gli altri sono i più comuni qui.
const ZONES = ["Europe/Rome", "Europe/London", "UTC", "America/New_York", "Asia/Tokyo"];

function formatRun(iso: string, timezone: string): string {
  const date = new Date(iso);
  return new Intl.DateTimeFormat("it-IT", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(date);
}

export function CronPicker({
  expr,
  timezone,
  onExpr,
  onTimezone,
}: {
  expr: string;
  timezone: string;
  onExpr: (value: string) => void;
  onTimezone: (value: string) => void;
}) {
  const [preview, setPreview] = useState<CronPreview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      previewCron(expr, timezone)
        .then((value) => {
          if (cancelled) return;
          setPreview(value);
          setError("");
        })
        .catch((reason: unknown) => {
          if (cancelled) return;
          setPreview(null);
          setError(reason instanceof Error ? reason.message : "Espressione non valida");
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [expr, timezone]);

  const zones = ZONES.includes(browserZone()) ? ZONES : [browserZone(), ...ZONES];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((preset) => (
          <button
            key={preset.expr}
            type="button"
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              expr === preset.expr
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-border text-muted hover:bg-surface-raised hover:text-foreground"
            }`}
            onClick={() => onExpr(preset.expr)}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <input
          className="min-w-[12rem] flex-1 rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm outline-none focus:border-muted"
          value={expr}
          onChange={(event) => onExpr(event.target.value)}
          spellCheck={false}
          aria-label="Espressione cron"
        />
        <select
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-muted"
          value={timezone}
          onChange={(event) => onTimezone(event.target.value)}
          aria-label="Fuso orario del trigger"
        >
          {zones.map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </select>
      </div>

      {error ? (
        <p className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : preview ? (
        <div className="rounded-lg border border-border bg-surface-raised/40 px-3 py-2">
          <p className="flex items-center gap-2 text-sm">
            <CalendarClock size={14} className="shrink-0 text-accent" />
            {preview.description}
          </p>
          {preview.next_runs.length ? (
            <ul className="mt-1.5 space-y-0.5 text-xs text-muted">
              {preview.next_runs.map((run) => (
                <li key={run}>Prossima: {formatRun(run, timezone)}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1.5 text-xs text-warning">
              Nessuna esecuzione nei prossimi 12 mesi: l'espressione è valida ma non scatta mai.
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
