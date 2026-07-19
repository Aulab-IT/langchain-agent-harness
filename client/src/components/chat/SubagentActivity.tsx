import { Bot, ChevronRight, CircleCheck, GitBranch, PauseCircle, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import {
  deriveSubagentInvocations,
  deriveSubagentRouting,
  formatElapsed,
  type RoutingActivity,
  type SubagentInvocation,
} from "../../lib/sessionActivity";
import type { RunEvent } from "../../types";

function Card({ invocation }: { invocation: SubagentInvocation }) {
  const [open, setOpen] = useState(false);
  const running = invocation.status === "running";
  const paused = invocation.status === "paused";
  return (
    <article className="overflow-hidden rounded-lg border border-border bg-background/40">
      <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface-raised" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <ChevronRight size={14} className={`shrink-0 text-muted transition-transform ${open ? "rotate-90" : ""}`} />
        {running ? <span className="h-3.5 w-3.5 shrink-0 rounded-full border-2 border-border border-t-info animate-spin-slow" /> : paused ? <PauseCircle size={15} className="shrink-0 text-warning" /> : invocation.status === "error" ? <TriangleAlert size={15} className="shrink-0 text-danger" /> : <CircleCheck size={15} className="shrink-0 text-success" />}
        <Bot size={14} className="shrink-0 text-info" />
        <code className="min-w-0 flex-1 truncate text-xs font-semibold">{invocation.name}</code>
        {invocation.routingTaskId ? <code className="text-[10px] text-muted">{invocation.routingTaskId}</code> : null}
        <span className="text-xs text-muted">{running ? "in corso" : paused ? "attesa approvazione" : invocation.objectiveMet === false ? "output incompleto" : formatElapsed(invocation.elapsedMs)}</span>
      </button>
      {open ? <div className="space-y-2 border-t border-border px-3 py-2 text-xs"><p className="text-muted">{invocation.description}</p>{invocation.inputArtifacts.length ? <p className="text-muted">Input: {invocation.inputArtifacts.join(", ")}</p> : null}{invocation.outputArtifacts.length ? <p className="text-success">Output: {invocation.outputArtifacts.join(", ")}</p> : null}{invocation.tools.length ? <ul className="space-y-1">{invocation.tools.map((tool) => <li key={tool.id} className="rounded border border-border bg-surface px-2 py-1.5"><div className="flex justify-between gap-2"><code>{tool.tool}</code><span className={tool.status === "error" ? "text-danger" : "text-muted"}>{tool.status === "running" ? "in corso" : tool.status === "paused" ? "attesa approvazione" : formatElapsed(tool.elapsedMs)}</span></div>{tool.output ? <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap text-muted">{tool.output}</pre> : null}</li>)}</ul> : null}{invocation.output ? <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-border p-2 text-muted">{invocation.output}</pre> : null}</div> : null}
    </article>
  );
}

function RoutingCard({ routing }: { routing: RoutingActivity }) {
  const warning = routing.status === "fallback" || routing.status === "not_followed";
  const label = {
    planning: "Analisi roster in corso",
    planned: `${routing.tasks.length} deleghe pianificate`,
    executing: "Piano deleghe in esecuzione",
    direct: routing.decision === "direct_root" ? "Esecuzione diretta con tool root" : "Risposta diretta scelta",
    fallback: "Fallback nativo attivo",
    followed: "Piano deleghe avviato",
    not_followed: "Piano deleghe non seguito",
  }[routing.status];
  return <article className={`rounded-lg border px-3 py-2 text-xs ${warning ? "border-warning/30 bg-warning/10" : "border-info/20 bg-info/5"}`}>
    <div className="flex items-center gap-2">
      <GitBranch size={14} className={warning ? "text-warning" : "text-info"} />
      <strong className="flex-1">{label}</strong>
      {routing.strategy ? <code className="text-muted">{routing.strategy}</code> : null}
    </div>
    {routing.roster.length ? <p className="mt-1 text-muted">Roster: {routing.roster.join(", ")}</p> : null}
    {routing.tasks.length ? <ul className="mt-2 space-y-1">{routing.tasks.map((task) => <li key={task.id} className="rounded border border-border/70 bg-background/40 px-2 py-1.5"><div className="flex gap-2"><code>{task.id}</code><span>→</span><strong>{task.selectedAgent}</strong><span className="ml-auto text-muted">{task.status}{task.attempt > 1 ? ` · tentativo ${task.attempt}` : ""}</span></div>{task.dependsOn.length ? <p className="text-muted">Dopo: {task.dependsOn.join(", ")}</p> : null}<p className="mt-0.5 text-muted">{task.objective}</p>{task.outputArtifacts.length ? <p className="mt-1 text-success">Artifact: {task.outputArtifacts.join(", ")}</p> : null}</li>)}</ul> : null}
    {routing.rationale ? <p className="mt-1.5 text-muted">{routing.rationale}</p> : null}
    {routing.rejectedMatches.length ? <ul className="mt-1.5 space-y-1 text-warning">{routing.rejectedMatches.map((match, index) => <li key={`${match.agent}-${index}`}>Match scartato: <code>{match.agent}</code>{match.reason ? ` · ${match.reason}` : ""}</li>)}</ul> : null}
    {routing.error ? <p className="mt-1.5 text-warning">{routing.error}</p> : null}
    {routing.missingAgents.length ? <p className="mt-1.5 text-warning">Non completati: {routing.missingAgents.join(", ")}</p> : null}
  </article>;
}

export function SubagentActivity({ events }: { events: RunEvent[] }) {
  const invocations = useMemo(() => deriveSubagentInvocations(events), [events]);
  const routing = useMemo(() => deriveSubagentRouting(events), [events]);
  if (!invocations.length && !routing) return null;
  const active = invocations.filter((item) => item.status === "running").length;
  const paused = invocations.filter((item) => item.status === "paused").length;
  return <section className="space-y-2 border-t border-border px-4 py-3">{routing ? <RoutingCard routing={routing} /> : null}<div className="flex items-center gap-2 text-xs text-muted"><Bot size={13} /><span>{invocations.length} subagent{invocations.length === 1 ? "" : "i"}</span>{active ? <span>· {active} in corso</span> : null}{paused ? <span>· {paused} in attesa</span> : null}</div>{invocations.map((item) => <Card key={item.invocationId} invocation={item} />)}</section>;
}
