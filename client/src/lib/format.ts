import type { AgentStatus, Run } from "../types";

export function timeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("it-IT", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function relativeLabel(value: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "adesso";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min fa`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h fa`;
  return new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short" }).format(
    new Date(value),
  );
}

export function runToAgentStatus(run: Run | null): AgentStatus {
  if (!run) return "idle";
  if (run.status === "waiting_approval" || run.status === "waiting_action") return "approval";
  if (run.status === "running" || run.status === "queued") return "thinking";
  if (run.status === "failed") return "error";
  return "idle";
}

export function runElapsedSeconds(run: Run | null): number | null {
  if (!run?.started_at) return null;
  const end = run.completed_at ? new Date(run.completed_at).getTime() : Date.now();
  return (end - new Date(run.started_at).getTime()) / 1000;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
