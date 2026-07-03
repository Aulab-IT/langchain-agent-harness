import type { AgentStatus } from "../../types";

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: "bg-muted-2",
  thinking: "bg-accent animate-pulse-dot",
  working: "bg-info",
  approval: "bg-warning",
  error: "bg-danger",
};

export function StatusDot({ status }: { status: AgentStatus }) {
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${STATUS_COLORS[status]}`}
      aria-hidden="true"
    />
  );
}
