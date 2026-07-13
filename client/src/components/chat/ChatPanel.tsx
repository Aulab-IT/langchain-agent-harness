import { BrainCircuit, Clock3, MessageSquareText, Sparkles, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import type {
  ModelOverride,
  Run,
  RunEvent,
  RuntimeModel,
  RuntimeSkill,
  SessionDetail,
  SessionFile,
} from "../../types";
import { latestSelectedModel } from "../../lib/sessionActivity";
import { isTerminalRunStatus, RUN_STATUS_LABELS } from "../../lib/runStatus";
import { ChatComposer } from "./ChatComposer";
import { ChatMessage } from "./ChatMessage";
import { MarkdownContent } from "./MarkdownContent";
import { ThinkingTrace } from "./ThinkingTrace";
import { SubagentActivity } from "./SubagentActivity";

export function ChatPanel({
  session,
  run,
  events,
  pending,
  skills,
  models,
  onSend,
  onUpload,
  onRemovePending,
  onTimeline,
  onStop,
  onToggleAutoApprove,
  onSessionModel,
  className = "",
}: {
  session: SessionDetail;
  run: Run | null;
  skills: RuntimeSkill[];
  models: RuntimeModel[];
  events: RunEvent[];
  pending: SessionFile[];
  onSend: (content: string) => void;
  onUpload: (files: FileList | null) => void;
  onRemovePending: (name: string) => void;
  onTimeline: () => void;
  onStop: () => void;
  onToggleAutoApprove: (enabled: boolean) => void;
  onSessionModel: (override: ModelOverride) => void;
  className?: string;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);

  // Se l'utente ha scrollato in alto per rileggere, un nuovo evento/delta non deve
  // riportarlo giu': l'auto-scroll resta attivo solo finche' e' gia' vicino al fondo.
  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      stickToBottom.current = distance < 96;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    stickToBottom.current = true;
  }, [session.id]);

  const onDragEnter = (event: DragEvent<HTMLElement>) => {
    if (!Array.from(event.dataTransfer.types).includes("Files")) return;
    event.preventDefault();
    dragDepth.current += 1;
    setDragging(true);
  };
  const onDragOver = (event: DragEvent<HTMLElement>) => {
    if (Array.from(event.dataTransfer.types).includes("Files")) event.preventDefault();
  };
  const onDragLeave = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  };
  const onDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    if (event.dataTransfer.files.length) onUpload(event.dataTransfer.files);
  };

  const active = Boolean(run && !isTerminalRunStatus(run.status));
  // Ogni continuazione produce un nuovo flusso di delta: senza ripartire dall'ultimo
  // confine, la bolla in streaming concatenerebbe tutte le iterazioni del run.
  const liveText = useMemo(() => {
    let start = 0;
    for (let index = events.length - 1; index >= 0; index -= 1) {
      if (events[index]?.type === "assistant.iteration") {
        start = index + 1;
        break;
      }
    }
    return events
      .slice(start)
      .filter((event) => event.type === "assistant.delta")
      .map((event) => String(event.payload.text ?? ""))
      .join("");
  }, [events]);

  useEffect(() => {
    if (!stickToBottom.current) return;
    endRef.current?.scrollIntoView({ block: "end", behavior: active ? "auto" : "smooth" });
  }, [session.messages, events.length, active, liveText]);

  const liveModel = useMemo(() => latestSelectedModel(events), [events]);
  const visibleMessages = session.messages.filter((message) => message.role !== "system");
  const lastUserIndex = (() => {
    for (let index = visibleMessages.length - 1; index >= 0; index -= 1) {
      if (visibleMessages[index]?.role === "user") return index;
    }
    return -1;
  })();
  const hasAssistantReply =
    lastUserIndex >= 0 &&
    visibleMessages.slice(lastUserIndex + 1).some((message) => message.role === "assistant");
  const showStreaming = Boolean(liveText && (active || !hasAssistantReply));

  return (
    <section
      className={`relative grid h-full max-h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-xl border border-border bg-surface ${className}`}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {dragging ? (
        <div
          className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-accent bg-background/90"
          aria-hidden="true"
        >
          <Upload size={24} className="text-accent" />
          <strong className="text-base">Rilascia per allegare</strong>
          <span className="text-sm text-muted">I file entrano nel workspace della conversazione</span>
        </div>
      ) : null}

      <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3 lg:px-5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
            <MessageSquareText size={18} />
          </div>
          <div>
            <h2 className="text-sm font-semibold">Conversazione</h2>
            <p className="text-xs text-muted">
              {visibleMessages.length} messaggi
              {active ? " · run attivo" : ""}
            </p>
          </div>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted hover:bg-surface-raised hover:text-foreground"
          onClick={onTimeline}
        >
          <Clock3 size={14} />
          Timeline
        </button>
      </div>

      <div ref={messagesRef} className="min-h-0 overflow-y-auto overscroll-contain p-5">
        <div className="space-y-5">
        {visibleMessages.length ? (
          visibleMessages.map((message) => (
            <ChatMessage key={message.id} message={message} sessionId={session.id} />
          ))
        ) : (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
            <BrainCircuit size={28} className="text-accent" />
            <strong className="text-base">Sessione pronta</strong>
            <span className="text-sm text-muted">Carica file o assegna un obiettivo.</span>
          </div>
        )}
        {showStreaming || active ? (
          <article className="flex gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
              <Sparkles size={16} />
            </div>
            <div className="min-w-0 max-w-[85%] flex-1">
              <div className="mb-1.5 flex items-center gap-2">
                <strong className="text-sm">Agente</strong>
                {liveModel ? (
                  <span className="rounded-full border border-border px-2 py-0.5 font-mono text-xs text-muted">
                    {liveModel}
                  </span>
                ) : null}
                <span className="rounded-full border border-border px-2 py-0.5 font-mono text-xs text-muted">
                  {active ? "in corso" : "streaming"}
                </span>
              </div>
              <div className="overflow-hidden rounded-xl border border-border bg-surface-raised">
                {active ? (
                  // Durante il run: stato pulito. L'azione corrente sta in evidenza; il flusso
                  // grezzo del modello (riassunti, note intermedie) è ripiegato di default, così
                  // l'attesa non è un muro di testo. La risposta finale appare come messaggio
                  // normale quando il run termina.
                  <>
                    <ThinkingTrace events={events} run={run} />
                    <SubagentActivity events={events} />
                    {liveText ? (
                      <details className="border-t border-border px-4 py-2">
                        <summary className="cursor-pointer select-none text-xs text-muted hover:text-foreground">
                          Output in tempo reale
                        </summary>
                        <div className="mt-2 max-h-48 overflow-y-auto text-sm text-muted">
                          <MarkdownContent content={liveText} sessionId={session.id} />
                        </div>
                      </details>
                    ) : null}
                  </>
                ) : showStreaming ? (
                  <div className="px-4 py-3 text-base leading-relaxed">
                    <MarkdownContent content={liveText} sessionId={session.id} />
                  </div>
                ) : (
                  <div className="flex items-center gap-2 px-4 py-3 text-sm text-muted">
                    <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-border border-t-accent animate-spin-slow" />
                    Elaborazione in corso…
                  </div>
                )}
              </div>
            </div>
          </article>
        ) : null}
        {!active ? <SubagentActivity events={events} /> : null}
        {run && isTerminalRunStatus(run.status) && run.status !== "completed" && run.error ? (
          <div className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
            {RUN_STATUS_LABELS[run.status]}: {run.error}
          </div>
        ) : null}
        <div ref={endRef} />
        </div>
      </div>

      <ChatComposer
        disabled={active}
        files={pending}
        skills={skills}
        models={models}
        autoApprove={session.auto_approve}
        sessionModel={session.model_override}
        onSend={onSend}
        onUpload={onUpload}
        onDeleteFile={onRemovePending}
        onStop={onStop}
        onToggleAutoApprove={onToggleAutoApprove}
        onSessionModel={onSessionModel}
      />
    </section>
  );
}
