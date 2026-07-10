import { Bot, ChevronRight, CircleCheck, Sparkles, TriangleAlert, Wrench } from "lucide-react";
import { memo, useState } from "react";
import { formatElapsed, type ToolStep } from "../../lib/sessionActivity";

function StepIcon({ status }: { status: ToolStep["status"] }) {
  if (status === "running") {
    return (
      <span className="inline-block h-3.5 w-3.5 shrink-0 rounded-full border-2 border-border border-t-accent animate-spin-slow" />
    );
  }
  if (status === "error") return <TriangleAlert size={14} className="shrink-0 text-danger" />;
  return <CircleCheck size={14} className="shrink-0 text-success" />;
}

const StepRow = memo(function StepRow({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(false);
  const hasDetail = Boolean(step.args || step.output);

  return (
    <li className="border-b border-border last:border-b-0">
      <button
        type="button"
        className="flex w-full items-center gap-2.5 px-4 py-2 text-left hover:bg-surface-raised/50 disabled:cursor-default"
        onClick={() => setOpen((current) => !current)}
        disabled={!hasDetail}
        aria-expanded={hasDetail ? open : undefined}
      >
        {hasDetail ? (
          <ChevronRight
            size={13}
            className={`shrink-0 text-muted transition-transform ${open ? "rotate-90" : ""}`}
          />
        ) : (
          <span className="w-[13px] shrink-0" />
        )}
        <StepIcon status={step.status} />
        <code className="shrink-0 font-mono text-xs text-foreground">{step.tool}</code>
        {step.skill ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-accent/20 bg-accent/10 px-2 py-0.5 text-xs text-accent">
            <Sparkles size={10} /> {step.skill}
          </span>
        ) : null}
        {step.subagent ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-border bg-surface px-2 py-0.5 text-xs text-muted">
            <Bot size={10} /> {step.subagent}
          </span>
        ) : null}
        <span className="min-w-0 flex-1 truncate text-xs text-muted">{step.args}</span>
        <span className="shrink-0 font-mono text-xs text-muted">
          {formatElapsed(step.elapsedMs)}
        </span>
      </button>
      {open && hasDetail ? (
        <div className="space-y-2 bg-background/50 px-4 pb-3 pt-1">
          {step.args ? (
            <div>
              <div className="mb-1 text-xs font-medium text-muted">Argomenti</div>
              <pre className="max-h-40 overflow-auto rounded-lg border border-border bg-background p-2.5 font-mono text-xs leading-relaxed">
                {step.args}
              </pre>
            </div>
          ) : null}
          {step.output ? (
            <div>
              <div className="mb-1 text-xs font-medium text-muted">Output</div>
              <pre className="max-h-56 overflow-auto rounded-lg border border-border bg-background p-2.5 font-mono text-xs leading-relaxed">
                {step.output}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
});

export function ToolSteps({ steps }: { steps: ToolStep[] }) {
  if (!steps.length) return null;
  const running = steps.filter((step) => step.status === "running").length;

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-surface-raised">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs text-muted">
        <Wrench size={13} />
        <span className="font-medium text-foreground">
          {steps.length} {steps.length === 1 ? "passo" : "passi"}
        </span>
        {running ? <span>· {running} in corso</span> : null}
      </div>
      <ul>
        {steps.map((step) => (
          <StepRow key={step.id} step={step} />
        ))}
      </ul>
    </section>
  );
}
