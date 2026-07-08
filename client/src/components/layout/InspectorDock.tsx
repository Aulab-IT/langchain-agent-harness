import {
  Box,
  ChevronUp,
  Cpu,
  Layers3,
  MessageSquare,
  PanelBottom,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type { InspectorTab } from "../../lib/constants";
import { describeCurrentAction } from "../../lib/runTrace";
import type {
  ActivityItem,
  Run,
  RunEvent,
  RuntimeStatus,
  SessionFile,
  SessionSandbox,
  Usage,
} from "../../types";
import { InspectorRail } from "./InspectorRail";

const HEIGHT_KEY = "harness.inspector.height";
const OPEN_KEY = "harness.inspector.open";
const MIN_HEIGHT = 200;

function clampHeight(value: number): number {
  const max = Math.round(window.innerHeight * 0.8);
  return Math.max(MIN_HEIGHT, Math.min(max, value));
}

type DockProps = {
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  sessionId: string;
  sessionTitle: string;
  messageCount: number;
  files: SessionFile[];
  skills: ActivityItem[];
  tools: ActivityItem[];
  usage: Usage;
  contextWindow: number;
  runtime: RuntimeStatus;
  sessionSandbox: SessionSandbox;
  run: Run | null;
  events: RunEvent[];
  onUpload: (files: FileList | null) => void;
  onDeleteFile: (name: string) => void;
  onStopSandbox: () => void;
};

const STATUS_DOT: Record<string, string> = {
  running: "bg-accent",
  queued: "bg-accent",
  waiting_approval: "bg-warning",
  failed: "bg-danger",
};

export function InspectorDock(props: DockProps) {
  const {
    usage,
    contextWindow,
    runtime,
    sessionSandbox,
    run,
    files,
    sessionTitle,
    messageCount,
    events,
    onTabChange,
  } = props;
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) !== "false");
  const [height, setHeight] = useState(() => {
    const stored = Number(localStorage.getItem(HEIGHT_KEY));
    return stored >= MIN_HEIGHT ? stored : 360;
  });
  const dragging = useRef(false);

  useEffect(() => {
    localStorage.setItem(OPEN_KEY, String(open));
  }, [open]);
  useEffect(() => {
    localStorage.setItem(HEIGHT_KEY, String(height));
  }, [height]);

  const startDrag = useCallback((event: ReactPointerEvent) => {
    event.preventDefault();
    dragging.current = true;
    const startY = event.clientY;
    const startHeight = Number(localStorage.getItem(HEIGHT_KEY)) || 360;
    const onMove = (moveEvent: PointerEvent) => {
      if (!dragging.current) return;
      setHeight(clampHeight(startHeight + (startY - moveEvent.clientY)));
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.userSelect = "";
    };
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }, []);

  const percent = Math.min(100, Math.round((usage.input_tokens / contextWindow) * 100));
  const status = run?.status ?? "idle";
  const active = Boolean(run && ["queued", "running", "waiting_approval"].includes(run.status));
  const current = describeCurrentAction(events, run);

  // Barra di stato compatta (chiuso), full-width, edge-to-edge — solo desktop.
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          if (active) onTabChange("trace");
          setOpen(true);
        }}
        className="hidden shrink-0 items-center gap-4 border-t border-border bg-surface px-4 py-2 text-xs text-muted hover:bg-surface-raised xl:flex"
        aria-label={active ? "Apri trace live" : "Apri inspector"}
      >
        <span className="flex items-center gap-1.5 font-medium text-foreground">
          <PanelBottom size={14} /> {active ? "Trace live" : "Inspector"}
        </span>
        <span className="max-w-[220px] truncate text-foreground/80">{sessionTitle}</span>
        {active ? (
          <span className="min-w-0 flex-1 truncate text-foreground">
            In corso: {current.title}
            {current.detail ? <span className="text-muted"> · {current.detail}</span> : null}
          </span>
        ) : null}
        <span className="flex items-center gap-1.5">
          <MessageSquare size={13} /> {messageCount}
        </span>
        <span className="hidden items-center gap-1.5 md:flex">
          <span className={`h-2 w-2 rounded-full ${STATUS_DOT[status] ?? "bg-muted-2"}`} />
          {status}
        </span>
        <span className="hidden items-center gap-1.5 lg:flex">
          <Cpu size={13} /> {runtime.model}
        </span>
        <span className="flex items-center gap-1.5">
          <Layers3 size={13} /> {usage.input_tokens.toLocaleString("it-IT")} tok · {percent}%
        </span>
        <span className="hidden items-center gap-1.5 lg:flex">
          <Box size={13} /> sandbox {sessionSandbox.state}
        </span>
        <span className="hidden md:inline">{files.length} file</span>
        <span className="ml-auto flex items-center gap-1 text-accent">
          <ChevronUp size={14} /> {active ? "Espandi trace" : "Espandi"}
        </span>
      </button>
    );
  }

  return (
    <div className="hidden shrink-0 flex-col border-t border-border xl:flex" style={{ height }}>
      <div
        onPointerDown={startDrag}
        className="group relative flex h-3 shrink-0 cursor-ns-resize items-center justify-center bg-surface"
        role="separator"
        aria-label="Ridimensiona inspector"
      >
        <div className="h-1 w-12 rounded-full bg-border transition-colors group-hover:bg-accent" />
      </div>
      <div className="min-h-0 flex-1">
        <InspectorRail {...props} variant="dock" onClose={() => setOpen(false)} />
      </div>
    </div>
  );
}
