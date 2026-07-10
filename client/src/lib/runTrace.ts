import type { Run, RunEvent } from "../types";

export type TraceTone = "running" | "success" | "warning" | "danger" | "muted" | "info";

export type TraceEventDescription = {
  title: string;
  detail: string | null;
  subject: string | null;
  tone: TraceTone;
};

export type CurrentAction = {
  title: string;
  detail: string | null;
  startedAt: string | null;
  tone: TraceTone;
  event: RunEvent | null;
};

const TRACE_NOISE = new Set(["assistant.delta", "usage.live"]);

export function asTraceText(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

export function formatTraceDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return minutes ? `${minutes}m ${secs.toString().padStart(2, "0")}s` : `${secs}s`;
}

export function compactTraceValue(value: unknown, limit = 180): string | null {
  const text =
    typeof value === "string"
      ? value
      : value == null
        ? ""
        : JSON.stringify(value, null, 0);
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return null;
  return clean.length > limit ? `${clean.slice(0, limit - 1)}…` : clean;
}

function parsedArgs(payload: Record<string, unknown>): Record<string, unknown> | null {
  const args = payload.args;
  if (args && typeof args === "object" && !Array.isArray(args)) {
    return args as Record<string, unknown>;
  }
  if (typeof args !== "string") return null;
  try {
    const parsed = JSON.parse(args);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export function traceSubject(event: RunEvent): string | null {
  const payload = event.payload ?? {};
  return (
    asTraceText(payload.tool) ??
    asTraceText(payload.skill) ??
    asTraceText(payload.action) ??
    asTraceText(payload.name) ??
    asTraceText(payload.model) ??
    asTraceText(payload.status) ??
    null
  );
}

export function traceCommand(event: RunEvent): string | null {
  const payload = event.payload ?? {};
  const args = parsedArgs(payload);
  return (
    asTraceText(payload.command) ??
    asTraceText(args?.command) ??
    asTraceText(args?.query) ??
    asTraceText(args?.url) ??
    asTraceText(args?.path) ??
    asTraceText(args?.file_path) ??
    compactTraceValue(payload.args, 220)
  );
}

function elapsedDetail(payload: Record<string, unknown>): string | null {
  return typeof payload.elapsed_ms === "number" ? `${payload.elapsed_ms} ms` : null;
}

function tokenDetail(payload: Record<string, unknown>): string | null {
  const total = asTraceText(payload.total_tokens);
  const input = asTraceText(payload.input_tokens);
  const output = asTraceText(payload.output_tokens);
  if (total) return `${total} token`;
  if (input || output) return `${input ?? "0"}/${output ?? "0"} token`;
  return null;
}

export function describeTraceEvent(event: RunEvent): TraceEventDescription {
  const payload = event.payload ?? {};
  const subject = traceSubject(event);
  const command = traceCommand(event);
  const elapsed = elapsedDetail(payload);
  const output = compactTraceValue(payload.output, 180);

  switch (event.type) {
    case "run.started":
      return { title: "Run avviato", detail: "GoalRunner in esecuzione", subject, tone: "running" };
    case "run.completed":
      return {
        title: "Run completato",
        detail: elapsed ?? compactTraceValue(payload, 180),
        subject,
        tone: "success",
      };
    case "run.failed":
      return {
        title: "Run fallito",
        detail: compactTraceValue(payload.error ?? payload, 180),
        subject,
        tone: "danger",
      };
    case "run.cancelled":
      return { title: "Run cancellato", detail: null, subject, tone: "warning" };
    case "agent.started":
      return {
        title: `Modello ${subject ?? "agent"} avviato`,
        detail: "Preparazione ragionamento e tool",
        subject,
        tone: "running",
      };
    case "config.selected":
      return {
        title: `Config ${asTraceText(payload.arm) ?? "runtime"} selezionata`,
        detail: compactTraceValue(payload.fingerprint ?? payload.source ?? payload, 180),
        subject: asTraceText(payload.arm),
        tone: "info",
      };
    case "assistant.delta":
      return {
        title: "Risposta modello in streaming",
        detail: compactTraceValue(payload.text, 180),
        subject,
        tone: "running",
      };
    case "assistant.iteration":
      return {
        title: `Iterazione ${asTraceText(payload.iteration) ?? "?"}`,
        detail: "Il criterio di uscita non è stato raggiunto: l'agente continua.",
        subject,
        tone: "info",
      };
    case "assistant.completed":
      return {
        title: "Risposta finale salvata",
        detail: compactTraceValue(payload.message, 180),
        subject,
        tone: "success",
      };
    case "tool.started":
      return {
        title: `Tool ${subject ?? "sconosciuto"} in esecuzione`,
        detail: command,
        subject,
        tone: "running",
      };
    case "tool.completed":
      return {
        title: `Tool ${subject ?? "sconosciuto"} completato`,
        detail: [elapsed, output].filter(Boolean).join(" · ") || null,
        subject,
        tone: "success",
      };
    case "tool.failed":
      return {
        title: `Tool ${subject ?? "sconosciuto"} fallito`,
        detail: [elapsed, compactTraceValue(payload.error ?? payload.output, 180)]
          .filter(Boolean)
          .join(" · ") || null,
        subject,
        tone: "danger",
      };
    case "skill.started":
      return {
        title: `Skill ${subject ?? "sconosciuta"} caricata`,
        detail: "Progressive disclosure attiva",
        subject,
        tone: "running",
      };
    case "skill.completed":
      return {
        title: `Skill ${subject ?? "sconosciuta"} completata`,
        detail: null,
        subject,
        tone: "success",
      };
    case "approval.requested":
      return {
        title: `Richiesta approvazione: ${subject ?? "azione sensibile"}`,
        detail: command ?? compactTraceValue(payload.description, 180),
        subject,
        tone: "warning",
      };
    case "approval.auto":
      return {
        title: `Auto-approvazione: ${subject ?? "azione sensibile"}`,
        detail: command ?? compactTraceValue(payload.description, 180),
        subject,
        tone: "warning",
      };
    case "approval.resolved":
      return {
        title: payload.approved ? "Approvazione concessa" : "Approvazione rifiutata",
        detail: null,
        subject,
        tone: payload.approved ? "success" : "danger",
      };
    case "action.requested":
      return {
        title: `Azione utente richiesta: ${compactTraceValue(payload.title, 80) ?? "intervento"}`,
        detail: compactTraceValue(payload.instructions, 180),
        subject,
        tone: "warning",
      };
    case "action.resolved":
      return {
        title: payload.cancelled ? "Azione utente annullata" : "Azione utente completata",
        detail: null,
        subject,
        tone: payload.cancelled ? "danger" : "success",
      };
    case "grader.started":
      return {
        title: "Valutazione rubric avviata",
        detail: "Judge controlla qualità e completamento",
        subject,
        tone: "running",
      };
    case "grader.completed": {
      const passed = payload.passed ? "passata" : "non passata";
      const score = asTraceText(payload.score);
      return {
        title: `Valutazione rubric ${passed}`,
        detail: [score ? `score ${score}` : null, compactTraceValue(payload.feedback, 180)]
          .filter(Boolean)
          .join(" · ") || null,
        subject,
        tone: payload.passed ? "success" : "warning",
      };
    }
    case "usage.snapshot":
      return {
        title: "Snapshot token aggiornato",
        detail: tokenDetail(payload),
        subject,
        tone: "muted",
      };
    case "usage.updated":
      return {
        title: "Uso token finale aggiornato",
        detail: tokenDetail(payload),
        subject,
        tone: "info",
      };
    case "usage.live":
      return {
        title: "Uso token live aggiornato",
        detail: tokenDetail(payload),
        subject,
        tone: "muted",
      };
    case "file.created":
      return {
        title: `File creato: ${asTraceText(payload.name) ?? "nuovo file"}`,
        detail: compactTraceValue(payload.type ?? payload.size, 180),
        subject: asTraceText(payload.name),
        tone: "success",
      };
    case "file.updated":
      return {
        title: `File aggiornato: ${asTraceText(payload.name) ?? "file"}`,
        detail: compactTraceValue(payload.type ?? payload.size, 180),
        subject: asTraceText(payload.name),
        tone: "success",
      };
    default:
      return {
        title: subject ? `${event.type}: ${subject}` : `Evento ${event.type}`,
        detail: command ?? compactTraceValue(payload, 180),
        subject,
        tone: event.type.endsWith("failed") ? "danger" : "muted",
      };
  }
}

export function isTraceActionEvent(event: RunEvent): boolean {
  return !TRACE_NOISE.has(event.type);
}

function pendingToolEvent(events: RunEvent[]): RunEvent | null {
  const pending: RunEvent[] = [];
  for (const event of events) {
    const tool = asTraceText(event.payload?.tool);
    if (!tool) continue;
    if (event.type === "tool.started") {
      pending.push(event);
      continue;
    }
    if (event.type === "tool.completed" || event.type === "tool.failed") {
      const index = pending.findIndex((item) => asTraceText(item.payload?.tool) === tool);
      if (index >= 0) pending.splice(index, 1);
    }
  }
  return pending.sort((a, b) => b.id - a.id)[0] ?? null;
}

function pendingGraderEvent(events: RunEvent[]): RunEvent | null {
  let started: RunEvent | null = null;
  for (const event of events) {
    if (event.type === "grader.started") started = event;
    if (event.type === "grader.completed") started = null;
  }
  return started;
}

function latestEvent(events: RunEvent[], predicate: (event: RunEvent) => boolean): RunEvent | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event && predicate(event)) return event;
  }
  return null;
}

export function describeCurrentAction(events: RunEvent[], run: Run | null): CurrentAction {
  if (!run && events.length === 0) {
    return {
      title: "Nessun run attivo",
      detail: "Avvia un messaggio per vedere il trace live",
      startedAt: null,
      tone: "muted",
      event: null,
    };
  }

  if (run?.status === "queued") {
    return {
      title: "Run in coda",
      detail: "Attende slot di esecuzione",
      startedAt: run.started_at,
      tone: "running",
      event: null,
    };
  }

  if (run?.status === "waiting_approval") {
    const approval = latestEvent(events, (event) => event.type === "approval.requested");
    const described = approval ? describeTraceEvent(approval) : null;
    return {
      title: described?.title ?? "Attesa approvazione utente",
      detail: described?.detail ?? "Azione sensibile sospesa",
      startedAt: approval?.created_at ?? run.started_at,
      tone: "warning",
      event: approval,
    };
  }

  if (run?.status === "completed" || run?.status === "failed" || run?.status === "cancelled") {
    const terminal = latestEvent(events, (event) => event.type === `run.${run.status}`);
    const described = terminal ? describeTraceEvent(terminal) : null;
    const fallback = {
      completed: "Run completato",
      failed: "Run fallito",
      cancelled: "Run cancellato",
    } satisfies Record<typeof run.status, string>;
    return {
      title: described?.title ?? fallback[run.status],
      detail: described?.detail ?? run.error ?? null,
      startedAt: terminal?.created_at ?? run.completed_at ?? run.started_at,
      tone: described?.tone ?? (run.status === "completed" ? "success" : "danger"),
      event: terminal,
    };
  }

  const tool = pendingToolEvent(events);
  if (tool) {
    const described = describeTraceEvent(tool);
    return {
      title: described.title,
      detail: described.detail,
      startedAt: tool.created_at,
      tone: described.tone,
      event: tool,
    };
  }

  const grader = pendingGraderEvent(events);
  if (grader) {
    const described = describeTraceEvent(grader);
    return {
      title: described.title,
      detail: described.detail,
      startedAt: grader.created_at,
      tone: described.tone,
      event: grader,
    };
  }

  const streaming = latestEvent(events, (event) => event.type === "assistant.delta");
  const last = events[events.length - 1] ?? null;
  if (streaming && (!last || streaming.id >= last.id - 2)) {
    return {
      title: "Risposta modello in streaming",
      detail: compactTraceValue(streaming.payload?.text, 180),
      startedAt: streaming.created_at,
      tone: "running",
      event: streaming,
    };
  }

  const lastAction = latestEvent(events, isTraceActionEvent);
  if (lastAction) {
    const described = describeTraceEvent(lastAction);
    const title =
      lastAction.type === "tool.completed"
        ? `Modello valuta output di ${described.subject ?? "tool"}`
        : lastAction.type === "agent.started"
          ? described.title.replace("avviato", "in ragionamento")
          : described.title;
    return {
      title,
      detail: described.detail,
      startedAt: lastAction.created_at,
      tone: run?.status === "running" ? "running" : described.tone,
      event: lastAction,
    };
  }

  return {
    title: "Avvio GoalRunner",
    detail: "Preparazione run e contesto sessione",
    startedAt: run?.started_at ?? null,
    tone: "running",
    event: null,
  };
}
