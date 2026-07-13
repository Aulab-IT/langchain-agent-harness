import type { RunEvent } from "../types";

export type ToolStep = {
  id: number;
  tool: string;
  args: string;
  output: string;
  status: "running" | "paused" | "ok" | "error";
  elapsedMs: number | null;
  skill: string | null;
  subagent: string | null;
  startedAt: string;
};

export type SubagentInvocation = {
  invocationId: string;
  name: string;
  description: string;
  status: "running" | "paused" | "ok" | "error";
  elapsedMs: number | null;
  output: string;
  tools: ToolStep[];
  routingTaskId: string | null;
  attempt: number;
  objectiveMet: boolean | null;
  inputArtifacts: string[];
  outputArtifacts: string[];
};

export type RoutingTask = {
  id: string;
  objective: string;
  selectedAgent: string;
  dependsOn: string[];
  status: string;
  attempt: number;
  inputArtifacts: string[];
  outputArtifacts: string[];
};

export type RoutingActivity = {
  status:
    | "planning"
    | "planned"
    | "executing"
    | "direct"
    | "fallback"
    | "followed"
    | "not_followed";
  roster: string[];
  rationale: string;
  strategy: string;
  error: string;
  missingAgents: string[];
  tasks: RoutingTask[];
};

/**
 * Il nome del subagent non compare negli eventi: i grafi annidati ricevono solo
 * `ls_agent_type: "subagent"` nel config. Lo si legge però dagli argomenti della chiamata
 * a `task`, che è il tool con cui l'agente principale delega.
 */
function subagentOf(tool: string, args: string): string | null {
  if (tool !== "task") return null;
  const match = /"subagent_type"\s*:\s*"([^"]+)"/.exec(args);
  return match ? match[1] : null;
}

export type ActivityEntry = {
  name: string;
  calls: number;
  totalMs: number;
  running: boolean;
  lastStatus: "ok" | "error" | "running" | "paused";
  lastAt: string;
};

const STEP_TYPES = new Set([
  "tool.started",
  "tool.resumed",
  "tool.paused",
  "tool.completed",
  "tool.failed",
  "subagent.tool.started",
  "subagent.tool.resumed",
  "subagent.tool.paused",
  "subagent.tool.completed",
  "subagent.tool.failed",
]);

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** Stato persistente del planner: roster, match, fallback e aderenza alle chiamate reali. */
export function deriveSubagentRouting(events: RunEvent[]): RoutingActivity | null {
  let routing: RoutingActivity | null = null;
  for (const event of events) {
    const payload = event.payload ?? {};
    if (event.type === "subagent.routing.started") {
      routing = {
        status: "planning",
        roster: strings(payload.agents),
        rationale: "",
        strategy: "",
        error: "",
        missingAgents: [],
        tasks: [],
      };
      continue;
    }
    if (!routing) continue;
    if (event.type === "subagent.routing.completed") {
      const tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
      routing.tasks = tasks.flatMap((raw): RoutingTask[] => {
        if (!raw || typeof raw !== "object") return [];
        const task = raw as Record<string, unknown>;
        return [{
          id: text(task.id),
          objective: text(task.objective),
          selectedAgent: text(task.selected_agent),
          dependsOn: strings(task.depends_on),
          status: "planned",
          attempt: 0,
          inputArtifacts: [],
          outputArtifacts: [],
        }];
      });
      routing.status = payload.delegate ? "planned" : "direct";
      routing.rationale = text(payload.rationale);
      routing.strategy = text(payload.strategy);
      continue;
    }
    if (event.type.startsWith("subagent.task.")) {
      const task = routing.tasks.find((item) => item.id === text(payload.routing_task_id));
      if (!task) continue;
      task.status = event.type.slice("subagent.task.".length);
      task.attempt = typeof payload.attempt === "number" ? payload.attempt : task.attempt;
      task.inputArtifacts = strings(payload.input_artifacts);
      task.outputArtifacts = strings(payload.output_artifacts);
      routing.status = "executing";
      continue;
    }
    if (event.type === "subagent.routing.failed") {
      routing.status = "fallback";
      routing.error = text(payload.error);
      continue;
    }
    if (event.type === "subagent.routing.followed") {
      routing.status = "followed";
      continue;
    }
    if (event.type === "subagent.routing.not_followed") {
      routing.status = "not_followed";
      routing.missingAgents = strings(payload.missing_agents);
    }
  }
  return routing;
}

/**
 * Ricostruisce le invocazioni dei tool dagli eventi del run.
 *
 * Gli eventi `tool.completed` / `tool.failed` non portano l'identificativo della chiamata,
 * solo il nome del tool: appaiamo ogni chiusura alla più vecchia invocazione ancora aperta
 * con lo stesso nome. Con chiamate parallele dello stesso tool l'abbinamento di durata e
 * output può quindi scambiarsi fra due righe; il conteggio e gli esiti restano corretti.
 */
export function deriveToolSteps(events: RunEvent[]): ToolStep[] {
  const steps: ToolStep[] = [];
  const open = new Map<string, ToolStep[]>();

  for (const event of events) {
    if (!STEP_TYPES.has(event.type)) continue;
    const tool = text(event.payload.tool);
    if (!tool) continue;
    const eventSubagent = text(event.payload.subagent) || null;
    const queueKey = `${eventSubagent ?? "root"}:${tool}`;

    if (event.type.endsWith(".resumed")) {
      const resumed = open.get(queueKey)?.[0];
      if (resumed) resumed.status = "running";
      continue;
    }

    if (event.type.endsWith(".started")) {
      const args = text(event.payload.args);
      const step: ToolStep = {
        id: event.id,
        tool,
        args,
        output: "",
        status: "running",
        elapsedMs: null,
        skill: text(event.payload.skill) || null,
        subagent: eventSubagent || subagentOf(tool, args),
        startedAt: event.created_at,
      };
      steps.push(step);
      const queue = open.get(queueKey) ?? [];
      queue.push(step);
      open.set(queueKey, queue);
      continue;
    }

    const step = open.get(queueKey)?.[0];
    if (!step) continue;
    if (event.type.endsWith(".paused")) {
      step.status = "paused";
      step.elapsedMs = typeof event.payload.elapsed_ms === "number"
        ? event.payload.elapsed_ms
        : null;
      continue;
    }
    open.get(queueKey)?.shift();
    step.status = event.type.endsWith(".failed") ? "error" : "ok";
    step.output = text(event.payload.output);
    const elapsed = event.payload.elapsed_ms;
    step.elapsedMs = typeof elapsed === "number" ? elapsed : null;
  }

  return steps;
}

/** Telemetria dedicata: una card per task, tool figli associati con invocation_id. */
export function deriveSubagentInvocations(events: RunEvent[]): SubagentInvocation[] {
  const byId = new Map<string, SubagentInvocation>();
  const childByCall = new Map<string, ToolStep>();
  for (const event of events) {
    const payload = event.payload ?? {};
    const invocationId = text(payload.invocation_id);
    if (!invocationId || !event.type.startsWith("subagent.")) continue;
    if (event.type === "subagent.started") {
      byId.set(invocationId, {
        invocationId,
        name: text(payload.subagent) || "subagent",
        description: text(payload.description),
        status: "running",
        elapsedMs: null,
        output: "",
        tools: [],
        routingTaskId: text(payload.routing_task_id) || null,
        attempt: typeof payload.attempt === "number" ? payload.attempt : 1,
        objectiveMet: null,
        inputArtifacts: strings(payload.input_artifacts),
        outputArtifacts: [],
      });
      continue;
    }
    const invocation = byId.get(invocationId);
    if (!invocation) continue;
    if (event.type === "subagent.paused") {
      invocation.status = "paused";
      continue;
    }
    if (event.type === "subagent.resumed") {
      invocation.status = "running";
      continue;
    }
    if (event.type === "subagent.completed" || event.type === "subagent.failed") {
      invocation.objectiveMet =
        typeof payload.objective_met === "boolean" ? payload.objective_met : null;
      invocation.status =
        event.type === "subagent.failed" || invocation.objectiveMet === false ? "error" : "ok";
      invocation.elapsedMs = typeof payload.elapsed_ms === "number" ? payload.elapsed_ms : null;
      invocation.output = text(payload.output);
      invocation.inputArtifacts = strings(payload.input_artifacts);
      invocation.outputArtifacts = strings(payload.output_artifacts);
      continue;
    }
    if (!event.type.startsWith("subagent.tool.")) continue;
    const callId = text(payload.tool_call_id) || `${event.id}`;
    if (event.type === "subagent.tool.started") {
      const step: ToolStep = {
        id: event.id,
        tool: text(payload.tool),
        args: text(payload.args),
        output: "",
        status: "running",
        elapsedMs: null,
        skill: text(payload.skill) || null,
        subagent: invocation.name,
        startedAt: event.created_at,
      };
      invocation.tools.push(step);
      childByCall.set(`${invocationId}:${callId}`, step);
      continue;
    }
    const step = childByCall.get(`${invocationId}:${callId}`);
    if (!step) continue;
    if (event.type === "subagent.tool.paused") {
      step.status = "paused";
      step.elapsedMs = typeof payload.elapsed_ms === "number" ? payload.elapsed_ms : null;
      continue;
    }
    if (event.type === "subagent.tool.resumed") {
      step.status = "running";
      continue;
    }
    step.status = event.type === "subagent.tool.failed" ? "error" : "ok";
    step.elapsedMs = typeof payload.elapsed_ms === "number" ? payload.elapsed_ms : null;
    step.output = text(payload.output);
  }
  return [...byId.values()];
}

function aggregate(steps: ToolStep[], key: (step: ToolStep) => string | null): ActivityEntry[] {
  const byName = new Map<string, ActivityEntry>();
  for (const step of steps) {
    const name = key(step);
    if (!name) continue;
    const entry = byName.get(name) ?? {
      name,
      calls: 0,
      totalMs: 0,
      running: false,
      lastStatus: "running" as const,
      lastAt: step.startedAt,
    };
    entry.calls += 1;
    entry.totalMs += step.elapsedMs ?? 0;
    entry.running = entry.running || step.status === "running";
    entry.lastStatus = step.status;
    entry.lastAt = step.startedAt;
    byName.set(name, entry);
  }
  return [...byName.values()].sort((a, b) => b.calls - a.calls);
}

/** Tool effettivamente chiamati in questa sessione — non quelli semplicemente disponibili. */
export function deriveToolActivity(steps: ToolStep[]): ActivityEntry[] {
  return aggregate(steps, (step) => step.tool);
}

/** Skill effettivamente lette in questa sessione, dedotte dai percorsi `/skills/<nome>/…`. */
export function deriveSkillActivity(steps: ToolStep[]): ActivityEntry[] {
  return aggregate(steps, (step) => step.skill);
}

/**
 * Il modello dichiarato dall'ultimo evento `model.selected`, o `null` se il router non si è
 * ancora pronunciato. Mostrare al suo posto `runtime.model` — il default configurato —
 * significherebbe dire all'utente che ha risposto un modello che potrebbe non aver risposto.
 */
export function latestSelectedModel(events: RunEvent[]): string | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.type === "model.selected") {
      const model = text(event.payload.model);
      if (model) return model;
    }
  }
  return null;
}

export function formatElapsed(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
