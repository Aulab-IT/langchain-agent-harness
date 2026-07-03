import type { ReactNode } from "react";

export function MetricChip({
  label,
  value,
  icon,
}: {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-surface-raised/50 px-3 py-1.5">
      {icon ? <span className="text-muted">{icon}</span> : null}
      <div className="min-w-0">
        <div className="text-xs text-muted">{label}</div>
        <div className="truncate text-sm font-medium">{value}</div>
      </div>
    </div>
  );
}
