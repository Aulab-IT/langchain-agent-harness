import type { Run, RunEvent } from "../types";
import { isTerminalRunStatus, RUN_STATUS_LABELS } from "./runStatus";

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

// context.snapshot scatta a ogni chiamata al modello: alimenta la barra del contesto, non la
// timeline. La compaction rilevata, invece, è un evento raro e importante — resta nel trace.
const TRACE_NOISE = new Set(["assistant.delta", "usage.live", "context.snapshot"]);

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

// Formato cronometro min:sec (es. 0:45, 9:26) per il timer generale del run: mostra sempre i
// minuti, così il tempo totale si legge come un orologio invece che come un mucchio di secondi.
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
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
  const toolDisplay = asTraceText(payload.tool_display_name);
  const toolServer = asTraceText(payload.mcp_server);
  return (
    (toolDisplay ? (toolServer ? `MCP · ${toolServer} · ${toolDisplay}` : toolDisplay) : null) ??
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
    case "run.partial_result":
      return {
        title: "Risultato parziale conservato",
        detail: asTraceText(payload.message) ?? compactTraceValue(payload.changed_files, 180),
        subject,
        tone: "warning",
      };
    case "run.incomplete":
    case "run.blocked_needs_human":
    case "run.failed_verification":
    case "run.budget_exceeded":
    case "run.security_stop":
    case "run.no_work": {
      const status = event.type.slice(4) as Run["status"];
      return {
        title: RUN_STATUS_LABELS[status],
        detail: asTraceText(payload.reason) ?? compactTraceValue(payload, 180),
        subject,
        tone: status === "no_work" ? "muted" : status === "security_stop" ? "danger" : "warning",
      };
    }
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
    case "model.selected":
      return {
        title: `Modello: ${asTraceText(payload.model) ?? "?"}`,
        detail: asTraceText(payload.reason) ?? "",
        subject: asTraceText(payload.model),
        tone: "info",
      };
    case "model.preflight.started":
      return {
        title: `Preflight ${asTraceText(payload.model) ?? "modello"}`,
        detail: `Verifica disponibilità provider ${asTraceText(payload.provider) ?? "?"}`,
        subject: asTraceText(payload.model),
        tone: "running",
      };
    case "model.preflight.completed":
      return {
        title: `Preflight ${asTraceText(payload.model) ?? "modello"} superato`,
        detail: payload.cached ? "Risultato valido in cache" : elapsed,
        subject: asTraceText(payload.model),
        tone: "success",
      };
    case "model.preflight.failed":
      return {
        title: `Preflight ${asTraceText(payload.model) ?? "modello"} fallito`,
        detail: compactTraceValue(payload.error, 180),
        subject: asTraceText(payload.model),
        tone: "danger",
      };
    case "model.started":
      return {
        title: `Modello ${asTraceText(payload.model) ?? "?"} in elaborazione`,
        detail: `Chiamata ${asTraceText(payload.call_id) ?? "modello"}`,
        subject: asTraceText(payload.model),
        tone: "running",
      };
    case "model.completed":
      return {
        title: `Modello ${asTraceText(payload.model) ?? "?"} completato`,
        detail: elapsed,
        subject: asTraceText(payload.model),
        tone: "success",
      };
    case "model.failed":
      return {
        title: `Modello ${asTraceText(payload.model) ?? "?"} fallito`,
        detail: [elapsed, compactTraceValue(payload.error, 180)].filter(Boolean).join(" · ") || null,
        subject: asTraceText(payload.model),
        tone: "danger",
      };
    case "model.retrying":
      return {
        title: `Retry modello ${asTraceText(payload.attempt) ?? "?"}/${asTraceText(payload.max_attempts) ?? "?"}`,
        detail: asTraceText(payload.message),
        subject: asTraceText(payload.model),
        tone: "warning",
      };
    case "model.retry_exhausted":
    case "model.request_failed":
    case "model.error":
      return {
        title: "Errore provider modello",
        detail: `${asTraceText(payload.exception_type) ?? "errore"} · ${asTraceText(payload.message) ?? "nessun dettaglio"}${payload.request_id ? ` · ${asTraceText(payload.request_id)}` : ""}`,
        subject: asTraceText(payload.model),
        tone: "danger",
      };
    case "model.escalated":
      return {
        title: `Gradino superiore: ${asTraceText(payload.tier) ?? "?"}`,
        detail: "L'iterazione precedente non ha superato il criterio di uscita.",
        subject: asTraceText(payload.tier),
        tone: "warning",
      };
    case "subagent.routing.started":
      return {
        title: "Routing subagent avviato",
        detail: `Roster: ${compactTraceValue(payload.agents, 180) ?? "vuoto"}`,
        subject: null,
        tone: "running",
      };
    case "subagent.routing.completed": {
      const tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
      const rejected = Array.isArray(payload.rejected_matches)
        ? payload.rejected_matches
            .map((raw) => {
              if (!raw || typeof raw !== "object") return null;
              const item = raw as Record<string, unknown>;
              const agent = asTraceText(item.agent);
              const reason = asTraceText(item.reason);
              return agent ? `${agent}${reason ? `: ${reason}` : ""}` : null;
            })
            .filter(Boolean)
            .join(" · ")
        : "";
      const matches = tasks
        .map((task) => {
          if (!task || typeof task !== "object") return null;
          const item = task as Record<string, unknown>;
          const agent = asTraceText(item.selected_agent);
          const objective = asTraceText(item.objective);
          return agent ? `${agent}${objective ? `: ${objective}` : ""}` : null;
        })
        .filter(Boolean)
        .join(" · ");
      return {
        title: payload.delegate
          ? `Routing: ${tasks.length} deleghe pianificate`
          : payload.decision === "direct_root"
            ? "Routing: esecuzione diretta con tool root"
            : "Routing: risposta diretta",
        detail: [
          elapsed,
          matches,
          rejected ? `match scartato ${rejected}` : null,
          !matches ? compactTraceValue(payload.rationale, 180) : null,
        ].filter(Boolean).join(" · ") || null,
        subject: null,
        tone: payload.delegate ? "info" : "muted",
      };
    }
    case "subagent.routing.failed":
      return {
        title: "Routing subagent non disponibile",
        detail: `${compactTraceValue(payload.error, 180) ?? "errore sconosciuto"} · fallback nativo attivo`,
        subject: null,
        tone: "warning",
      };
    case "subagent.routing.retry":
      return {
        title: "Routing: retry JSON",
        detail: compactTraceValue(payload.reason, 180),
        subject: null,
        tone: "warning",
      };
    case "tool.routing.completed": {
      const recommended = Array.isArray(payload.recommended)
        ? payload.recommended.filter((item): item is string => typeof item === "string")
        : [];
      const readable = Array.isArray(payload.recommended_tools)
        ? payload.recommended_tools
            .map((raw) => {
              if (!raw || typeof raw !== "object") return null;
              const item = raw as Record<string, unknown>;
              const name = asTraceText(item.display_name) ?? asTraceText(item.name);
              const server = asTraceText(item.server);
              return name ? (server ? `MCP · ${server} · ${name}` : name) : null;
            })
            .filter(Boolean)
        : [];
      return {
        title: payload.required
          ? "Tool routing: accesso runtime richiesto"
          : recommended.length
            ? "Tool routing: suggerimento opzionale"
            : "Tool routing: nessun tool necessario",
        detail: [
          recommended.length ? `consigliato ${(readable.length ? readable : recommended).join(" → ")}` : null,
          compactTraceValue(payload.rationale, 180),
          asTraceText(payload.strategy),
        ].filter(Boolean).join(" · ") || null,
        subject: recommended[0] ?? null,
        tone: payload.required ? "info" : recommended.length ? "muted" : "success",
      };
    }
    case "tool.routing.used":
      return {
        title: `Tool consigliato usato: ${asTraceText(payload.tool) ?? "?"}`,
        detail: compactTraceValue(payload.recommended, 180),
        subject: asTraceText(payload.tool),
        tone: "success",
      };
    case "subagent.routing.followed":
      return {
        title: "Piano subagent completato",
        detail: `Agent: ${compactTraceValue(payload.agents, 180) ?? "?"}`,
        subject: null,
        tone: "success",
      };
    case "subagent.routing.not_followed":
      return {
        title: "Piano subagent non seguito",
        detail: `Non completati: ${compactTraceValue(payload.missing_agents, 180) ?? "?"}`,
        subject: null,
        tone: "warning",
      };
    case "subagent.started":
      return {
        title: `Subagent ${asTraceText(payload.subagent) ?? "?"} avviato`,
        detail: [
          asTraceText(payload.routing_task_id),
          compactTraceValue(payload.description, 180),
        ].filter(Boolean).join(" · ") || null,
        subject: asTraceText(payload.subagent),
        tone: "running",
      };
    case "subagent.paused":
      return {
        title: `Subagent ${asTraceText(payload.subagent) ?? "?"} in attesa approvazione`,
        detail: asTraceText(payload.routing_task_id),
        subject: asTraceText(payload.subagent),
        tone: "warning",
      };
    case "subagent.resumed":
      return {
        title: `Subagent ${asTraceText(payload.subagent) ?? "?"} ripreso`,
        detail: asTraceText(payload.routing_task_id),
        subject: asTraceText(payload.subagent),
        tone: "running",
      };
    case "subagent.completed":
      return {
        title: payload.objective_met === false
          ? `Subagent ${asTraceText(payload.subagent) ?? "?"}: output incompleto`
          : `Subagent ${asTraceText(payload.subagent) ?? "?"} completato`,
        detail: [elapsed, compactTraceValue(payload.output_artifacts, 180)]
          .filter(Boolean)
          .join(" · ") || null,
        subject: asTraceText(payload.subagent),
        tone: payload.objective_met === false ? "warning" : "success",
      };
    case "subagent.failed":
      return {
        title: `Subagent ${asTraceText(payload.subagent) ?? "?"} fallito`,
        detail: elapsed,
        subject: asTraceText(payload.subagent),
        tone: "danger",
      };
    case "subagent.retry_stopped":
      return {
        title: `Retry fermato: ${asTraceText(payload.subagent) ?? "subagent"}`,
        detail: asTraceText(payload.reason),
        subject: asTraceText(payload.tool),
        tone: "warning",
      };
    case "subagent.task.queued":
    case "subagent.task.reassigned":
    case "subagent.task.waiting":
    case "subagent.task.ready":
    case "subagent.task.paused":
    case "subagent.task.resumed":
    case "subagent.task.completed":
    case "subagent.task.incomplete":
    case "subagent.task.failed":
    case "subagent.task.blocked": {
      const state = event.type.slice("subagent.task.".length);
      const tone: TraceTone = state === "completed"
        ? "success"
        : ["failed", "blocked"].includes(state)
          ? "danger"
          : ["incomplete", "paused"].includes(state)
            ? "warning"
            : "info";
      return {
        title: `Task ${asTraceText(payload.routing_task_id) ?? "?"}: ${state}`,
        detail: [
          asTraceText(payload.selected_agent),
          compactTraceValue(payload.used_tools, 120),
          compactTraceValue(payload.review_verdict, 60),
          compactTraceValue(payload.output_artifacts ?? payload.error, 180),
        ].filter(Boolean).join(" · ") || null,
        subject: asTraceText(payload.routing_task_id),
        tone,
      };
    }
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
    case "tool.paused":
      return {
        title: `Tool ${subject ?? "sconosciuto"} in attesa approvazione`,
        detail: [elapsed, command].filter(Boolean).join(" · ") || null,
        subject,
        tone: "warning",
      };
    case "tool.resumed":
      return {
        title: `Tool ${subject ?? "sconosciuto"} ripreso`,
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
      const vetoed = payload.safety_vetoed === true;
      const passed = payload.passed ? "passata" : "non passata";
      const score = asTraceText(payload.score);
      return {
        title: vetoed
          ? "Valutazione rubric — VETO di sicurezza"
          : `Valutazione rubric ${passed}`,
        detail: [
          vetoed ? "punteggio limitato dalla sicurezza" : null,
          score ? `score ${score}` : null,
          compactTraceValue(payload.feedback, 180),
        ]
          .filter(Boolean)
          .join(" · ") || null,
        subject,
        tone: vetoed ? "danger" : payload.passed ? "success" : "warning",
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
    case "context.compaction.started":
      return {
        title: "Compaction manuale avviata",
        detail: "Analisi e riduzione del contesto in corso",
        subject,
        tone: "running",
      };
    case "context.compaction.detected": {
      const manual = payload.mode === "manual";
      return {
        title: manual ? "Riduzione manuale rilevata" : "Compaction automatica",
        detail: `${asTraceText(payload.tokens_before) ?? "?"} → ${
          asTraceText(payload.tokens_after) ?? "?"
        } token (${asTraceText(payload.tokens_reclaimed) ?? "0"} liberati)`,
        subject,
        tone: "info",
      };
    }
    case "context.compaction.completed":
      return {
        title: "Compaction manuale completata",
        detail: asTraceText(payload.message),
        subject,
        tone: "success",
      };
    case "context.compaction.no_work":
      return {
        title: "Contesto già compatto",
        detail: "Nessuna riduzione necessaria; nessun altro task eseguito.",
        subject,
        tone: "muted",
      };
    case "context.compaction.failed":
      return {
        title: "Compaction non riuscita",
        detail: asTraceText(payload.message),
        subject,
        tone: "danger",
      };
    case "context.tool_output.offloaded":
      return {
        title: `Output ${asTraceText(payload.tool) ?? "tool"} scaricato dal contesto`,
        detail: `${asTraceText(payload.tokens_reclaimed) ?? "0"} token recuperati · ${asTraceText(payload.reference) ?? "workspace"}`,
        subject: asTraceText(payload.tool),
        tone: "success",
      };
    case "budget.updated":
      return {
        title: "Budget run aggiornato",
        detail: `call +${asTraceText(payload.call_input_tokens) ?? "0"} input / +${asTraceText(payload.call_output_tokens) ?? "0"} output · cumulativo ${tokenDetail(payload) ?? "0 token"}`,
        subject: asTraceText(payload.call_kind),
        tone: "info",
      };
    case "budget.retry_estimated":
      return {
        title: "Costo retry stimato",
        detail: `${asTraceText(payload.estimated_failed_input_tokens) ?? "0"} input token · $${asTraceText(payload.estimated_failed_cost_usd) ?? "0"}`,
        subject: asTraceText(payload.call_kind),
        tone: "warning",
      };
    case "budget.warning":
      return {
        title: `Budget run al ${asTraceText(payload.level_percent) ?? "?"}%`,
        detail: `corrente ${tokenDetail(payload) ?? "0 token"} · prossima proiezione ${asTraceText(payload.projected_tokens) ?? "?"}`,
        subject: asTraceText(payload.exceeded_dimension),
        tone: "warning",
      };
    case "budget.exceeded":
      return {
        title: `Limite raggiunto: ${asTraceText(payload.dimension) ?? "budget run"}`,
        detail: asTraceText(payload.reason) ?? compactTraceValue(payload, 180),
        subject: asTraceText(payload.dimension),
        tone: "warning",
      };
    case "subagent.finalization.started":
      return {
        title: "Subagent in finalizzazione",
        detail: `prossima call ${asTraceText(payload.next_model_call) ?? "?"}/${asTraceText(payload.max_model_calls) ?? "?"} · verifiche opzionali sospese`,
        subject: asTraceText(payload.call_kind),
        tone: "warning",
      };
    case "subagent.finalization.forced":
      return {
        title: "Call finale riservata alla consegna",
        detail: `call ${asTraceText(payload.next_model_call) ?? "?"}/${asTraceText(payload.max_model_calls) ?? "?"} · tool disabilitati`,
        subject: asTraceText(payload.call_kind),
        tone: "warning",
      };
    case "memory.truncated":
      return {
        title: "Memoria troncata",
        detail: `Superato il limite di ${asTraceText(payload.max_chars) ?? "?"} caratteri.`,
        subject,
        tone: "warning",
      };
    case "trigger.skipped":
      return {
        title: "Trigger saltato",
        detail: `${asTraceText(payload.name) ?? "trigger"}: sessione già in esecuzione`,
        subject: asTraceText(payload.name),
        tone: "warning",
      };
    case "mcp.server.failed":
      return {
        title: `Server MCP non raggiungibile: ${asTraceText(payload.server) ?? "?"}`,
        detail: compactTraceValue(payload.error, 180),
        subject: asTraceText(payload.server),
        tone: "danger",
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

function pendingModelEvent(events: RunEvent[]): RunEvent | null {
  const pending = new Map<string, RunEvent>();
  for (const event of events) {
    const callId = asTraceText(event.payload?.call_id);
    if (!callId) continue;
    if (event.type === "model.started") pending.set(callId, event);
    if (event.type === "model.completed" || event.type === "model.failed") pending.delete(callId);
  }
  return [...pending.values()].sort((a, b) => b.id - a.id)[0] ?? null;
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

  if (run && isTerminalRunStatus(run.status)) {
    const terminal = latestEvent(events, (event) => event.type === `run.${run.status}`);
    const described = terminal ? describeTraceEvent(terminal) : null;
    return {
      title: described?.title ?? RUN_STATUS_LABELS[run.status],
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

  const model = pendingModelEvent(events);
  if (model) {
    const described = describeTraceEvent(model);
    return {
      title: described.title,
      detail: described.detail,
      startedAt: model.created_at,
      tone: described.tone,
      event: model,
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
