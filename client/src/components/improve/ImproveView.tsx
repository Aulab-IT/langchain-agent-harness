import {
  Check,
  FileText,
  FlaskConical,
  Rocket,
  RotateCcw,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  applyImprovement,
  clearCanary,
  clearOverrides,
  evaluateImprovement,
  getCanaryStatus,
  getImprovement,
  listConfigVersions,
  listImprovements,
  restoreConfigVersion,
  runImprove,
} from "../../api";
import { relativeLabel } from "../../lib/format";
import type {
  CanaryAnalysis,
  CanaryConfig,
  CaseResult,
  ConfigVersion,
  EvaluationArtifact,
  ImprovementSummary,
  ImproveResult,
  RuntimeStatus,
} from "../../types";
import { MarkdownContent } from "../chat/MarkdownContent";

export function ImproveView({ runtime }: { runtime: RuntimeStatus }) {
  const [items, setItems] = useState<ImprovementSummary[]>([]);
  const [versions, setVersions] = useState<ConfigVersion[]>([]);
  const [result, setResult] = useState<ImproveResult | null>(null);
  const [content, setContent] = useState("");
  const [evaluation, setEvaluation] = useState<EvaluationArtifact | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [overrides, setOverrides] = useState<Record<string, unknown>>(runtime.overrides ?? {});
  const [canary, setCanary] = useState(runtime.canary);
  const [canaryStatus, setCanaryStatus] = useState<CanaryAnalysis | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [proposals, configVersions, liveCanary] = await Promise.all([
        listImprovements(),
        listConfigVersions(),
        getCanaryStatus(),
      ]);
      setItems(proposals);
      setVersions(configVersions);
      setCanaryStatus(liveCanary.status === "inactive" ? null : liveCanary);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Caricamento miglioramenti fallito");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const canaryFingerprint = canary?.candidate_fingerprint ?? "";
  useEffect(() => {
    if (!canaryFingerprint) {
      setCanaryStatus(null);
      return;
    }
    let active = true;
    const poll = async () => {
      try {
        const status = await getCanaryStatus();
        if (active) setCanaryStatus(status.status === "inactive" ? null : status);
      } catch {
        // Poll best-effort: azioni esplicite continuano a mostrare eventuali errori.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 15_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [canaryFingerprint]);

  const generate = async () => {
    if (busy) return;
    setBusy("generate");
    setError("");
    setContent("");
    setEvaluation(null);
    try {
      setResult(await runImprove(100));
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Generazione proposta fallita");
    } finally {
      setBusy("");
    }
  };

  const open = async (name: string) => {
    try {
      const detail = await getImprovement(name);
      setContent(detail.content);
      setEvaluation(detail.evaluation);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Apertura proposta fallita");
    }
  };

  const evaluate = async (name: string) => {
    if (
      !window.confirm(
        "Eseguire baseline e candidato sull'eval set? Usa chiamate modello e può richiedere alcuni minuti.",
      )
    ) {
      return;
    }
    setBusy(`eval:${name}`);
    setError("");
    try {
      setEvaluation(await evaluateImprovement(name));
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Evaluation fallita");
    } finally {
      setBusy("");
    }
  };

  const promote = async (name: string, mode: "canary" | "full") => {
    const label = mode === "canary" ? "attivare canary al 20%" : "promuovere al 100%";
    if (!window.confirm(`${label} per ${name}?`)) return;
    setBusy(`${mode}:${name}`);
    setError("");
    try {
      const promotion = await applyImprovement(name, mode);
      setOverrides(promotion.active);
      setCanary(promotion.canary);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Promotion fallita");
    } finally {
      setBusy("");
    }
  };

  const resetOverrides = async () => {
    if (!window.confirm("Rimuovere config attiva e canary? La config corrente sarà versionata.")) {
      return;
    }
    try {
      await clearOverrides();
      setOverrides({});
      setCanary(null);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Reset override fallito");
    }
  };

  const stopCanary = async () => {
    try {
      await clearCanary();
      setCanary(null);
      setCanaryStatus(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Rollback canary fallito");
    }
  };

  const restore = async (version: ConfigVersion) => {
    if (!window.confirm(`Ripristinare versione ${version.id}?`)) return;
    setBusy(`restore:${version.id}`);
    try {
      const response = await restoreConfigVersion(version.id);
      setOverrides(response.overrides);
      setCanary(null);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Rollback fallito");
    } finally {
      setBusy("");
    }
  };

  const overrideKeys = Object.keys(overrides);

  return (
    <section className="mx-auto w-full max-w-5xl space-y-4">
      <div className="rounded-xl border border-border bg-surface">
        <div className="flex items-center gap-3 border-b border-border px-6 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-accent/20 bg-accent/10 text-accent">
            <TrendingUp size={18} />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-semibold">Miglioramenti verificati</h2>
            <p className="text-sm text-muted">
              Trace → proposta → evaluation paired → canary → promotion o rollback.
            </p>
          </div>
        </div>

        <div className="space-y-3 p-6">
          <p className="text-sm text-muted">
            Soglia e rubric restano congelate. Override ammessi:{" "}
            <code className="text-foreground">system_prompt_addendum</code> e{" "}
            <code className="text-foreground">harness_max_tool_calls</code>.
          </p>
          {error ? <p className="text-sm text-danger">{error}</p> : null}
          <button
            type="button"
            onClick={generate}
            disabled={Boolean(busy) || !runtime.configured}
            className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent hover:bg-accent-soft disabled:opacity-50"
          >
            <Sparkles size={16} />
            {busy === "generate" ? "Analisi in corso…" : "Genera proposta"}
          </button>
        </div>

        {canary ? (
          <CanaryLiveCard
            canary={canary}
            analysis={canaryStatus}
            onStop={stopCanary}
            onPromote={() => promote(canary.source, "full")}
            busy={Boolean(busy)}
          />
        ) : null}

        {overrideKeys.length ? (
          <div className="border-t border-border px-6 py-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-2">
                Config attiva
              </p>
              <button
                type="button"
                onClick={resetOverrides}
                className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted hover:text-danger"
              >
                <RotateCcw size={12} />
                Azzera
              </button>
            </div>
            {overrideKeys.map((key) => (
              <div key={key} className="flex justify-between gap-3 text-sm">
                <code className="text-muted">{key}</code>
                <code className="max-w-[60%] truncate">{String(overrides[key])}</code>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {result ? (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h3 className="text-sm font-semibold">Ultima proposta · {result.name}</h3>
          <p className="mt-2 text-sm text-muted">{result.summary || "(nessuna sintesi)"}</p>
          <pre className="mt-3 overflow-x-auto rounded-lg border border-border p-3 font-mono text-xs">
            {JSON.stringify(result.overrides, null, 2)}
          </pre>
          <p className="mt-2 text-xs text-muted">
            Non applicabile finché evaluation gate non passa.
          </p>
        </div>
      ) : null}

      {evaluation ? <EvaluationCard evaluation={evaluation} /> : null}

      <div className="rounded-xl border border-border bg-surface">
        <div className="border-b border-border px-6 py-4">
          <h3 className="text-sm font-semibold">Proposte salvate ({items.length})</h3>
        </div>
        <div className="divide-y divide-border">
          {items.length ? (
            items.map((item) => (
              <div key={item.name} className="flex flex-wrap items-center gap-2 px-6 py-3">
                <button
                  type="button"
                  onClick={() => open(item.name)}
                  className="flex min-w-0 flex-1 items-center gap-3 text-left"
                >
                  <FileText size={15} className="shrink-0 text-muted" />
                  <span className="min-w-0 flex-1 truncate font-mono text-sm">{item.name}</span>
                  <StatusLabel status={item.evaluation_status} />
                  <span className="text-xs text-muted">{relativeLabel(item.modified_at)}</span>
                </button>
                <button
                  type="button"
                  onClick={() => evaluate(item.name)}
                  disabled={Boolean(busy)}
                  className="rounded-lg border border-border px-2.5 py-1 text-xs disabled:opacity-50"
                >
                  {busy === `eval:${item.name}` ? "Valutazione…" : "Valuta"}
                </button>
                {item.evaluation_status === "passed" ? (
                  <>
                    <button
                      type="button"
                      onClick={() => promote(item.name, "canary")}
                      disabled={Boolean(busy)}
                      className="flex items-center gap-1 rounded-lg border border-warning/40 px-2.5 py-1 text-xs text-warning"
                    >
                      <FlaskConical size={12} />
                      Canary
                    </button>
                    <button
                      type="button"
                      onClick={() => promote(item.name, "full")}
                      disabled={
                        Boolean(busy) ||
                        (canary?.source === item.name && canaryStatus?.status !== "passed")
                      }
                      className="flex items-center gap-1 rounded-lg border border-success/40 px-2.5 py-1 text-xs text-success"
                    >
                      <Rocket size={12} />
                      Promuovi
                    </button>
                  </>
                ) : null}
              </div>
            ))
          ) : (
            <p className="px-6 py-10 text-center text-sm text-muted">Nessuna proposta.</p>
          )}
        </div>
      </div>

      {versions.length ? (
        <div className="rounded-xl border border-border bg-surface">
          <div className="border-b border-border px-6 py-4">
            <h3 className="text-sm font-semibold">Versioni config</h3>
          </div>
          <div className="divide-y divide-border">
            {versions.slice(0, 10).map((version) => (
              <div key={version.id} className="flex items-center gap-3 px-6 py-3 text-sm">
                <Check size={14} className="text-success" />
                <code className="min-w-0 flex-1 truncate">{version.id}</code>
                <span className="text-xs text-muted">{version.source}</span>
                <button
                  type="button"
                  onClick={() => restore(version)}
                  disabled={Boolean(busy)}
                  className="rounded-lg border border-border px-2.5 py-1 text-xs"
                >
                  Ripristina
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {content ? (
        <div className="rounded-xl border border-border bg-surface p-6">
          <MarkdownContent content={content} />
        </div>
      ) : null}
    </section>
  );
}

function CanaryLiveCard({
  canary,
  analysis,
  onStop,
  onPromote,
  busy,
}: {
  canary: CanaryConfig;
  analysis: CanaryAnalysis | null;
  onStop: () => void;
  onPromote: () => void;
  busy: boolean;
}) {
  const status = analysis?.status ?? "collecting";
  const statusStyle =
    status === "passed"
      ? "text-success"
      : status === "failed"
        ? "text-danger"
        : "text-warning";
  const statusLabel =
    status === "passed" ? "gate live passato" : status === "failed" ? "gate live fallito" : "raccolta";
  return (
    <div className="space-y-3 border-t border-warning/30 bg-warning/5 px-6 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <FlaskConical size={16} className="text-warning" />
        <p className="flex-1 text-sm">
          Canary: <code>{canary.source}</code> · {Math.round(canary.fraction * 100)}% sessioni
        </p>
        <span className={`text-xs font-medium ${statusStyle}`}>{statusLabel}</span>
        {status === "passed" ? (
          <button
            type="button"
            onClick={onPromote}
            disabled={busy}
            className="flex items-center gap-1 rounded-lg border border-success/40 px-2.5 py-1 text-xs text-success disabled:opacity-50"
          >
            <Rocket size={12} />
            Promuovi 100%
          </button>
        ) : null}
        <button
          type="button"
          onClick={onStop}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs disabled:opacity-50"
        >
          <X size={12} />
          Annulla
        </button>
      </div>
      {analysis ? (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            <CanaryMetric label="Baseline live" value={analysis.baseline} />
            <CanaryMetric label="Canary live" value={analysis.canary} />
          </div>
          <p className="text-xs text-muted">
            Δ success {analysis.success_delta.toFixed(3)} · Δ grader{" "}
            {analysis.grader_delta.toFixed(3)} · token ratio {analysis.token_ratio.toFixed(2)} ·
            latency ratio {analysis.latency_ratio.toFixed(2)}
          </p>
          {analysis.reasons.length ? (
            <ul className="list-disc pl-5 text-xs text-muted">
              {analysis.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function CanaryMetric({
  label,
  value,
}: {
  label: string;
  value: CanaryAnalysis["baseline"];
}) {
  return (
    <div className="rounded-lg border border-border bg-surface/60 p-3 text-xs">
      <p className="font-medium text-foreground">{label}</p>
      <p className="mt-1 text-muted">
        {value.total_runs} run · success {(value.success_rate * 100).toFixed(0)}% · failure{" "}
        {(value.failure_rate * 100).toFixed(0)}%
      </p>
      <p className="text-muted">
        grader {value.grader_avg_score.toFixed(3)} · {value.avg_tokens} token ·{" "}
        {(value.avg_latency_ms / 1000).toFixed(1)}s
      </p>
    </div>
  );
}

function StatusLabel({ status }: { status: ImprovementSummary["evaluation_status"] }) {
  const style =
    status === "active"
      ? "text-accent"
      : status === "passed"
        ? "text-success"
        : status === "rejected"
          ? "text-danger"
          : status === "stale"
            ? "text-warning"
            : "text-muted";
  const label =
    status === "active"
      ? "attiva"
      : status === "passed"
        ? "gate passato"
        : status === "rejected"
          ? "respinta"
          : status === "stale"
            ? "da rivalutare"
            : "pending";
  return <span className={`shrink-0 text-xs ${style}`}>{label}</span>;
}

function EvaluationCard({ evaluation }: { evaluation: EvaluationArtifact }) {
  const { baseline_summary: baseline, candidate_summary: candidate, gate } = evaluation;
  const candidateById = new Map(evaluation.candidate.map((item) => [item.case_id, item]));
  return (
    <div className="rounded-xl border border-border bg-surface p-6">
      <div className="flex items-center gap-2">
        <FlaskConical size={16} className={gate.passed ? "text-success" : "text-danger"} />
        <h3 className="font-semibold">Evaluation {gate.passed ? "passata" : "respinta"}</h3>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <MetricColumn label="Baseline" value={baseline} />
        <MetricColumn label="Candidato" value={candidate} />
      </div>
      <p className="mt-3 text-xs text-muted">
        Δ qualità {gate.quality_delta.toFixed(3)} · Δ completion{" "}
        {gate.completion_delta.toFixed(3)} · token ratio {gate.token_ratio.toFixed(2)} · latency
        ratio {gate.latency_ratio.toFixed(2)}
      </p>
      {gate.reasons.length ? (
        <ul className="mt-3 list-disc pl-5 text-sm text-danger">
          {gate.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
      <div className="mt-5 space-y-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-2">
          Dettaglio casi
        </p>
        {evaluation.baseline.map((baselineCase) => {
          const candidateCase = candidateById.get(baselineCase.case_id);
          return (
            <div key={baselineCase.case_id} className="rounded-lg border border-border p-3">
              <p className="mb-2 font-mono text-sm">{baselineCase.case_id}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <CaseColumn label="Baseline" value={baselineCase} />
                {candidateCase ? <CaseColumn label="Candidato" value={candidateCase} /> : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MetricColumn({
  label,
  value,
}: {
  label: string;
  value: EvaluationArtifact["baseline_summary"];
}) {
  return (
    <div className="rounded-lg border border-border p-3 text-sm">
      <p className="font-medium">{label}</p>
      <p className="mt-1 text-muted">
        check {(value.check_pass_rate * 100).toFixed(0)}% · completion{" "}
        {(value.completion_rate * 100).toFixed(0)}%
      </p>
      <p className="text-xs text-muted">
        score check {value.avg_check_score.toFixed(3)}
      </p>
      <p className="text-xs text-muted">
        {value.total_tokens} token · {(value.elapsed_ms / 1000).toFixed(1)}s
      </p>
    </div>
  );
}

function CaseColumn({ label, value }: { label: string; value: CaseResult }) {
  const feedback = value.grader_feedback[value.grader_feedback.length - 1];
  return (
    <div className="rounded-md bg-surface-raised/40 p-3 text-xs">
      <p className="font-medium text-foreground">{label}</p>
      <p className="mt-1 text-muted">
        check {value.checks_passed ? "pass" : "fail"} ({value.check_score.toFixed(3)}) ·
        completion {value.protocol_completed ? "sì" : "no"} · iterazioni {value.iterations}
      </p>
      <p className="text-muted">
        {value.tokens} token · {(value.elapsed_ms / 1000).toFixed(1)}s
      </p>
      {value.check_failures.map((failure) => (
        <p key={failure} className="mt-1 text-danger">
          Check: {failure}
        </p>
      ))}
      {value.protocol_failures.map((failure) => (
        <p key={failure} className="mt-1 text-warning">
          Protocollo: {failure}
        </p>
      ))}
      {feedback ? <p className="mt-2 text-muted">Grader: {feedback}</p> : null}
      {value.error ? <p className="mt-1 text-danger">Errore: {value.error}</p> : null}
    </div>
  );
}
