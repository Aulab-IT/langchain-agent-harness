import { ChevronDown, Layers3, PanelRight, X } from "lucide-react";
import type { InspectorTab } from "../../lib/constants";
import type { ActivityEntry } from "../../lib/sessionActivity";
import { isTerminalRunStatus } from "../../lib/runStatus";
import type {
  Run,
  RunEvent,
  RuntimeStatus,
  SessionFile,
  SessionSandbox,
  Usage,
} from "../../types";
import { ContextPanel } from "../inspector/ContextPanel";
import { FilesPanel } from "../inspector/FilesPanel";
import { MemoryPanel } from "../inspector/MemoryPanel";
import { RunTracePanel } from "../inspector/RunTracePanel";
import { SandboxPanel } from "../inspector/SandboxPanel";
import { SessionActivityPanel } from "../inspector/SessionActivityPanel";

const TABS: Array<{ id: InspectorTab; label: string }> = [
  { id: "trace", label: "Trace" },
  { id: "files", label: "File" },
  { id: "capabilities", label: "Attività" },
  { id: "memory", label: "Memoria" },
  { id: "context", label: "Contesto" },
  { id: "sandbox", label: "Sandbox" },
];

export function InspectorRail({
  tab,
  onTabChange,
  sessionId,
  files,
  skills,
  tools,
  usage,
  contextWindow,
  runtime,
  sessionSandbox,
  run,
  events,
  onUpload,
  onDeleteFile,
  onStopSandbox,
  onCompact,
  variant = "rail",
  onClose,
}: {
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  sessionId: string;
  files: SessionFile[];
  skills: ActivityEntry[];
  tools: ActivityEntry[];
  usage: Usage;
  contextWindow: number;
  runtime: RuntimeStatus;
  sessionSandbox: SessionSandbox;
  run: Run | null;
  events: RunEvent[];
  onUpload: (files: FileList | null) => void;
  onDeleteFile: (name: string) => void;
  onStopSandbox: () => void;
  onCompact: () => Promise<string>;
  variant?: "rail" | "sheet" | "dock";
  onClose?: () => void;
}) {
  const shellClass =
    variant === "sheet"
      ? "fixed inset-x-0 bottom-0 z-40 flex h-[55vh] flex-col rounded-t-2xl border border-border bg-surface shadow-2xl xl:hidden"
      : variant === "dock"
        ? "flex h-full max-h-full min-h-0 flex-col overflow-hidden bg-surface"
        : "hidden h-full max-h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-surface xl:flex";

  return (
    <aside className={shellClass}>
      {variant === "sheet" ? (
        <div className="flex justify-center py-2">
          <div className="h-1 w-10 rounded-full bg-border" />
        </div>
      ) : null}
      <div className="flex shrink-0 items-center border-b border-border bg-surface">
        {variant === "sheet" && onClose ? (
          <button
            type="button"
            className="ml-2 rounded-lg p-2 text-muted hover:bg-surface-raised"
            aria-label="Chiudi inspector"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        ) : (
          <div className="hidden items-center gap-2 px-4 py-3 text-muted lg:flex">
            <PanelRight size={16} />
            <span className="text-xs font-medium uppercase tracking-wide">Inspector</span>
          </div>
        )}
        <div className="flex min-w-0 flex-1 overflow-x-auto">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`shrink-0 border-b-2 px-4 py-3 text-sm transition-colors ${
                tab === item.id
                  ? "border-accent bg-surface-raised font-medium text-foreground"
                  : "border-transparent text-muted hover:bg-surface-raised/50 hover:text-foreground"
              }`}
              onClick={() => onTabChange(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        {variant === "dock" && onClose ? (
          <button
            type="button"
            className="mr-2 shrink-0 rounded-lg p-2 text-muted hover:bg-surface-raised hover:text-foreground"
            aria-label="Comprimi pannello"
            onClick={onClose}
          >
            <ChevronDown size={16} />
          </button>
        ) : null}
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background">
        {tab === "trace" ? <RunTracePanel run={run} events={events} /> : null}
        {tab === "files" ? (
          <FilesPanel
            sessionId={sessionId}
            files={files}
            onUpload={onUpload}
            onDelete={onDeleteFile}
          />
        ) : null}
        {tab === "capabilities" ? (
          <SessionActivityPanel skills={skills} tools={tools} />
        ) : null}
        {tab === "memory" ? <MemoryPanel sessionId={sessionId} /> : null}
        {tab === "context" ? (
          <ContextPanel
            usage={usage}
            contextWindow={contextWindow}
            sessionId={sessionId}
            run={run}
            events={events}
            busy={!!run && !isTerminalRunStatus(run.status)}
            onCompact={onCompact}
          />
        ) : null}
        {tab === "sandbox" ? (
          <SandboxPanel
            runtime={runtime}
            sessionSandbox={sessionSandbox}
            run={run}
            events={events}
            onStop={onStopSandbox}
          />
        ) : null}
      </div>
    </aside>
  );
}

export function InspectorMobileTrigger({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="fixed bottom-5 right-5 z-30 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-4 py-2.5 text-sm font-medium shadow-lg xl:hidden"
      onClick={onClick}
    >
      <Layers3 size={16} />
      Inspector
    </button>
  );
}
