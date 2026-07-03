import type { ReactNode } from "react";

export function AppShell({ sidebar, children }: { sidebar: ReactNode; children: ReactNode }) {
  return (
    <div className="grid h-dvh max-h-dvh overflow-hidden lg:grid-cols-[260px_minmax(0,1fr)]">
      {sidebar}
      <main className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden">
        {children}
      </main>
    </div>
  );
}
