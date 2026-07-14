import {
  CheckCircle2,
  FileCheck2,
  Hash,
  RefreshCw,
  ShieldCheck,
  Terminal,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getRunEvidence } from "../../api";
import { formatFileSize } from "../../lib/format";
import type { Run, RunEvidence } from "../../types";
import { PanelEmpty, Spinner } from "../shared/PanelEmpty";

function ShortHash({ value }: { value: string }) {
  return (
    <code className="font-mono text-[11px] text-muted" title={value}>
      {value.slice(0, 12)}…
    </code>
  );
}

function StateIcon({ passed }: { passed: boolean }) {
  return passed ? (
    <CheckCircle2 size={15} className="shrink-0 text-success" />
  ) : (
    <XCircle size={15} className="shrink-0 text-danger" />
  );
}

export function EvidencePanel({ run }: { run: Run | null }) {
  const [evidence, setEvidence] = useState<RunEvidence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!run) return;
    setLoading(true);
    try {
      setEvidence(await getRunEvidence(run.id));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Lettura evidenze fallita");
    } finally {
      setLoading(false);
    }
  }, [run]);

  useEffect(() => {
    setEvidence(null);
    load().catch(() => undefined);
  }, [load]);

  if (!run) return <PanelEmpty>Avvia un run per produrre il dossier delle evidenze.</PanelEmpty>;
  if (loading && !evidence) return <PanelEmpty><Spinner label="Verifica evidenze…" /></PanelEmpty>;
  if (error) return <PanelEmpty>{error}</PanelEmpty>;
  if (!evidence?.manifest || !evidence.integrity) {
    return <PanelEmpty>Il manifest verrà congelato quando il run raggiunge uno stato terminale.</PanelEmpty>;
  }

  const { manifest, integrity } = evidence;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck
              size={17}
              className={manifest.contract.passed && integrity.valid ? "text-success" : "text-danger"}
            />
            <h3 className="text-sm font-semibold">Dossier del run</h3>
          </div>
          <p className="mt-1 text-xs text-muted">
            Contratto {manifest.contract.passed ? "soddisfatto" : "non soddisfatto"} · integrità{" "}
            {integrity.valid ? "confermata" : "compromessa"}
          </p>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs hover:bg-surface-raised disabled:opacity-50"
          onClick={() => load()}
          disabled={loading}
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          Verifica integrità
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
        <section>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
            Contratto · {manifest.contract.task_kind}
          </h4>
          <div className="space-y-2">
            {manifest.contract.requirements.map((requirement) => (
              <div key={requirement.id} className="flex items-start gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                <StateIcon passed={requirement.passed} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">
                    {requirement.label}
                    {!requirement.required ? <span className="ml-1 text-xs text-muted">opzionale</span> : null}
                  </div>
                  <div className="text-xs text-muted">{requirement.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
            <FileCheck2 size={14} /> Artefatti · {manifest.artifacts.length}
          </h4>
          {manifest.artifacts.length ? (
            <div className="divide-y divide-border rounded-lg border border-border bg-surface">
              {manifest.artifacts.map((artifact) => {
                const check = integrity.checks.find((item) => item.id === `artifact:${artifact.path}`);
                return (
                  <div key={artifact.path} className="flex items-center gap-3 px-3 py-2">
                    <StateIcon passed={check?.passed ?? false} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium" title={artifact.path}>{artifact.path}</div>
                      <div className="flex items-center gap-2 text-xs text-muted">
                        {formatFileSize(artifact.size)} · <ShortHash value={artifact.sha256} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : <p className="text-xs text-muted">Nessun artefatto prodotto dal run.</p>}
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <div>
            <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
              <Terminal size={14} /> Comandi · {manifest.commands.length}
            </h4>
            <div className="space-y-2">
              {manifest.commands.map((command, index) => (
                <div key={`${command.tool_call_id}-${index}`} className="rounded-lg border border-border bg-surface px-3 py-2 text-xs">
                  <div className="flex items-center gap-2"><StateIcon passed={command.passed} /><strong>{command.tool}</strong></div>
                  <div className="mt-1 text-muted">exit {command.exit_code ?? "n/d"} · {command.elapsed_ms ?? 0} ms</div>
                  {command.arguments ? <pre className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap break-all rounded bg-background p-2 font-mono text-[10px] text-muted">{command.arguments}</pre> : null}
                  {command.result ? <pre className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap break-all rounded bg-background p-2 font-mono text-[10px] text-muted">{command.result}</pre> : null}
                </div>
              ))}
              {!manifest.commands.length ? <p className="text-xs text-muted">Nessun comando registrato.</p> : null}
            </div>
          </div>
          <div>
            <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
              <Hash size={14} /> Manifest
            </h4>
            <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs">
              <div className="flex items-center gap-2"><StateIcon passed={integrity.checks[0]?.passed ?? false} />SHA-256</div>
              <div className="mt-2 break-all font-mono text-[11px] text-muted">{manifest.manifest_sha256}</div>
              <div className="mt-2 text-muted">schema v{manifest.schema_version} · {manifest.terminal_status}</div>
            </div>
          </div>
        </section>

        <section>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
            Verifier · {manifest.verifiers.length}
          </h4>
          {manifest.verifiers.length ? (
            <div className="space-y-2">
              {manifest.verifiers.map((verifier, index) => (
                <div key={`${verifier.kind}-${verifier.event_id ?? index}`} className="flex items-start gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                  <StateIcon passed={verifier.passed} />
                  <div className="min-w-0 flex-1 text-xs">
                    <div className="font-medium">{verifier.kind}{verifier.score != null ? ` · score ${verifier.score.toFixed(3)}` : ""}</div>
                    {verifier.summary ? <p className="mt-1 text-muted">{verifier.summary}</p> : null}
                  </div>
                </div>
              ))}
            </div>
          ) : <p className="text-xs text-muted">Nessun verifier opzionale eseguito.</p>}
        </section>
      </div>
    </div>
  );
}
