import { Menu, Pencil, Trash2 } from "lucide-react";
import { runElapsedSeconds, runToAgentStatus } from "../../lib/format";
import type { AgentStatus, Run, RuntimeStatus, SessionDetail, Usage } from "../../types";
import { StatusDot } from "../shared/StatusDot";

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
  usage,
  onMenu,
  onRename,
  onDelete,
}: {
  session: SessionDetail | null;
  runtime: RuntimeStatus | null;
  run: Run | null;
  usage: Usage;
  onMenu: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const status = runToAgentStatus(run);
  const elapsed = runElapsedSeconds(run);
  const active = Boolean(run && ["queued", "running", "waiting_approval"].includes(run.status));

  return (
    <header className="shrink-0 border-b border-border bg-surface/80 px-3 py-2.5 backdrop-blur-sm lg:px-4">
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
            {runtime?.model ?? "—"} · {run?.status ?? "idle"}
            {elapsed !== null ? ` · ${elapsed.toFixed(1)}s` : ""}
            {active && usage.output_tokens_per_second
              ? ` · ~${usage.output_tokens_per_second} tok/s`
              : ""}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
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
