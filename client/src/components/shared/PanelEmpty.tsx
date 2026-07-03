import type { ReactNode } from "react";

export function PanelEmpty({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-muted">
      {children}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted">
      <span className="inline-block h-4 w-4 rounded-full border-2 border-border border-t-accent animate-spin-slow" />
      {label}
    </span>
  );
}
