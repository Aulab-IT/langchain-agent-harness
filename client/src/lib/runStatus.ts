import type { RunStatus } from "../types";

export const TERMINAL_RUN_STATUSES = new Set<RunStatus>([
  "completed",
  "incomplete",
  "blocked_needs_human",
  "failed_verification",
  "budget_exceeded",
  "security_stop",
  "no_work",
  "failed",
  "cancelled",
]);

export function isTerminalRunStatus(status: RunStatus): boolean {
  return TERMINAL_RUN_STATUSES.has(status);
}

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  queued: "In coda",
  running: "In esecuzione",
  waiting_approval: "Attesa approvazione",
  waiting_action: "Attesa azione",
  completed: "Completato",
  incomplete: "Incompleto",
  blocked_needs_human: "Bloccato: serve intervento",
  failed_verification: "Verifica fallita",
  budget_exceeded: "Budget esaurito",
  security_stop: "Stop di sicurezza",
  no_work: "Nessun lavoro",
  failed: "Fallito",
  cancelled: "Cancellato",
};
