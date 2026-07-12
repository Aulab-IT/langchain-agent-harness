import { Menu, Pencil, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { runToAgentStatus } from "../../lib/format";
import { formatClock } from "../../lib/runTrace";
import { modelLabel as resolveModelLabel } from "../../lib/modelOverride";
import { latestSelectedModel } from "../../lib/sessionActivity";
import type { AgentStatus, Run, RunEvent, RuntimeStatus, SessionDetail, Usage } from "../../types";
import { StatusDot } from "../shared/StatusDot";
import { NotificationBell } from "./NotificationBell";

function statusLabel(status: AgentStatus, runtime: RuntimeStatus | null): string {
  if (!runtime) return "Offline";
  if (!runtime.configured) return "Config richiesta";
  if (status === "approval") return "Approvazione";
  if (status === "thinking") return "Agent working";
  return "Live";
}

export function Topbar({
  session,
  runtime,
  run,
  events,
  usage,
  onMenu,
  onRename,
  onDelete,
}: {
  session: SessionDetail | null;
  runtime: RuntimeStatus | null;
  run: Run | null;
  events: RunEvent[];
  usage: Usage;
  onMenu: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const status = runToAgentStatus(run);
  // Il modello dichiarato dal router se un run è in corso; altrimenti quello che sappiamo già
  // che verrà usato, perché la sessione lo ha forzato; altrimenti il default, etichettato.
  const modelLabel =
    runtime && session
      ? resolveModelLabel(runtime.models, session.model_override, latestSelectedModel(events))
      : "—";
  const active = Boolean(run && ["queued", "running", "waiting_approval", "waiting_action"].includes(run.status));
  // Timer generale sincronizzato: ticka ogni secondo mentre il run è attivo, così i secondi
  // scorrono regolari invece di aggiornarsi solo quando arriva un evento (fermi da idle, a
  // scatti coi burst). Allineato al timer della card d'attesa (stesso started_at, stesso formato).
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  const elapsed = run?.started_at
    ? ((run.completed_at ? new Date(run.completed_at).getTime() : now) -
        new Date(run.started_at).getTime()) /
      1000
    : null;

  return (
    <header className="relative z-50 shrink-0 border-b border-border bg-surface/80 px-3 py-2.5 backdrop-blur-sm lg:px-4">
      <div className="flex min-w-0 items-center gap-2 lg:gap-3">
        <button
          type="button"
          className="shrink-0 rounded-lg border border-border p-1.5 text-muted hover:bg-surface-raised lg:hidden"
          aria-label="Apri menu"
          onClick={onMenu}
        >
          <Menu size={18} />
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <h1 className="truncate text-base font-semibold lg:text-lg">
              {session?.title ?? "Agent Studio"}
            </h1>
            {session ? (
              <button
                type="button"
                className="shrink-0 rounded p-1 text-muted hover:bg-surface-raised hover:text-foreground"
                aria-label="Rinomina sessione"
                onClick={onRename}
              >
                <Pencil size={13} />
              </button>
            ) : null}
            <span className="hidden items-center gap-1 rounded-full border border-border bg-surface-raised px-2 py-0.5 text-xs sm:inline-flex">
              <StatusDot status={status} />
              {statusLabel(status, runtime)}
            </span>
          </div>
          <p className="truncate font-mono text-[11px] text-muted">
            {modelLabel} · {run?.status ?? "idle"}
            {elapsed !== null ? ` · ${formatClock(elapsed)}` : ""}
            {active && usage.output_tokens_per_second
              ? ` · ~${usage.output_tokens_per_second} tok/s`
              : ""}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <NotificationBell />
          <span className="hidden items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted md:inline-flex">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            local
          </span>
          {session ? (
            <button
              type="button"
              className="rounded-lg border border-border p-1.5 text-muted hover:border-danger/40 hover:text-danger"
              aria-label="Elimina sessione"
              onClick={onDelete}
            >
              <Trash2 size={15} />
            </button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
