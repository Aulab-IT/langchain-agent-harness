import type { ReactNode } from "react";

export function AppShell({
  sidebar,
  dock,
  children,
}: {
  sidebar: ReactNode;
  dock?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex h-dvh max-h-dvh flex-col overflow-hidden">
      <div className="grid min-h-0 flex-1 overflow-hidden lg:grid-cols-[260px_minmax(0,1fr)]">
        {sidebar}
        <main className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden">
          {children}
        </main>
      </div>
      {dock}
    </div>
  );
}
