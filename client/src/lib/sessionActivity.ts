import type { RunEvent } from "../types";

export type ToolStep = {
  id: number;
  tool: string;
  args: string;
  output: string;
  status: "running" | "ok" | "error";
  elapsedMs: number | null;
  skill: string | null;
  subagent: string | null;
  startedAt: string;
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
  lastStatus: "ok" | "error" | "running";
  lastAt: string;
};

const STEP_TYPES = new Set(["tool.started", "tool.completed", "tool.failed"]);

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
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

    if (event.type === "tool.started") {
      const args = text(event.payload.args);
      const step: ToolStep = {
        id: event.id,
        tool,
        args,
        output: "",
        status: "running",
        elapsedMs: null,
        skill: text(event.payload.skill) || null,
        subagent: subagentOf(tool, args),
        startedAt: event.created_at,
      };
      steps.push(step);
      const queue = open.get(tool) ?? [];
      queue.push(step);
      open.set(tool, queue);
      continue;
    }

    const step = open.get(tool)?.shift();
    if (!step) continue;
    step.status = event.type === "tool.failed" ? "error" : "ok";
    step.output = text(event.payload.output);
    const elapsed = event.payload.elapsed_ms;
    step.elapsedMs = typeof elapsed === "number" ? elapsed : null;
  }

  return steps;
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

export function formatElapsed(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
