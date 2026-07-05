import { Box, Check, Square, ShieldCheck, TerminalSquare, X } from "lucide-react";
import type { Run, RunEvent, RuntimeStatus, SessionSandbox } from "../../types";

export function SandboxPanel({
  runtime,
  sessionSandbox,
  run,
  events,
  onStop,
}: {
  runtime: RuntimeStatus;
  sessionSandbox: SessionSandbox;
  run: Run | null;
  events: RunEvent[];
  onStop: () => void;
}) {
  const activeTool = [...events]
    .reverse()
    .find((event) => event.type === "tool.started" && event.payload.tool === "docker_exec");
  const completedAfter = activeTool
    ? events.some(
        (event) =>
          event.id > activeTool.id &&
          ["tool.completed", "tool.failed"].includes(event.type) &&
          event.payload.tool === "docker_exec",
      )
    : true;
  const commandRunning = Boolean(activeTool && !completedAfter);
  const command = [...events]
    .reverse()
    .find((event) => event.type === "approval.requested")?.payload.command;

  const dockerReady = runtime.sandbox.available;
  const containerRunning = sessionSandbox.running;
  const statusLabel = commandRunning
    ? "running"
    : run?.status === "waiting_approval"
      ? "approval"
      : containerRunning
        ? "active"
        : "idle";

  const badgeLabel = !dockerReady
    ? "Docker assente"
    : containerRunning
      ? "Attiva"
      : "On-demand";
  const busy = Boolean(run && ["queued", "running", "waiting_approval"].includes(run.status));

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold">Sandbox</h3>
          <p className="truncate text-xs text-muted">{sessionSandbox.image}</p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
              dockerReady
                ? containerRunning
                  ? "border-success/30 text-success"
                  : "border-border text-muted"
                : "border-danger/30 text-danger"
            }`}
          >
            {dockerReady ? <Check size={12} /> : <X size={12} />}
            {badgeLabel}
          </span>
          {containerRunning ? (
            <button
              type="button"
              onClick={onStop}
              disabled={busy}
              title={
                busy
                  ? "Impossibile fermare la sandbox mentre un run è in corso"
                  : "Ferma il container: si riavvia automaticamente al prossimo comando"
              }
              className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs text-muted hover:border-danger/40 hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Square size={10} fill="currentColor" />
              Ferma
            </button>
          ) : null}
        </div>
      </div>

      <div className="flex items-center gap-4 border-b border-border px-5 py-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-warning/20 bg-warning/10 text-warning">
          <Box size={24} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">Container per conversazione</div>
          <div className="text-xs text-muted">
            {containerRunning
              ? sessionSandbox.container ?? "Container attivo"
              : "Si avvia al primo docker_exec"}
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs">
          <ShieldCheck size={12} />
          {statusLabel}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 p-5">
        {[
          ["Rete", runtime.sandbox.network],
          ["Filesystem root", "Read-only"],
          ["Memoria", runtime.sandbox.memory],
          ["CPU", runtime.sandbox.cpu],
        ].map(([label, value]) => (
          <div
            key={label}
            className="rounded-lg border border-border bg-surface-raised/30 px-4 py-3"
          >
            <div className="text-xs text-muted">{label}</div>
            <div className="mt-1 font-mono text-sm font-medium">{value}</div>
          </div>
        ))}
      </div>

      <div className="mx-5 mb-5 flex items-center gap-3 rounded-lg border border-border bg-background px-4 py-3">
        <TerminalSquare size={16} className="shrink-0 text-muted" />
        <code className="min-w-0 flex-1 truncate font-mono text-sm">
          {commandRunning
            ? String(command || "docker_exec in esecuzione")
            : containerRunning
              ? "Container in attesa di comandi"
              : "Nessun container attivo"}
        </code>
        <span className="shrink-0 text-xs text-muted">{run?.status ?? sessionSandbox.state}</span>
      </div>
    </div>
  );
}
