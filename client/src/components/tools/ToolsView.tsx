import { AlertTriangle, ChevronDown, ChevronRight, Plug, Wrench } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { listTools } from "../../api";
import type { ToolDescriptor } from "../../types";
import { PanelEmpty } from "../shared/PanelEmpty";

const ORIGIN_LABELS: Record<string, string> = {
  "built-in": "Interno all'harness",
  "mcp:local_harness": "Server MCP locale",
};

// Disabilitare docker_exec non è una preferenza estetica: il grader di verifica cerca le sue
// esecuzioni riuscite per decidere se un obiettivo è stato davvero raggiunto.
const CAVEATS: Record<string, string> = {
  docker_exec:
    "È l'unico modo che l'agente ha di eseguire qualcosa. Senza, il grader non trova prove " +
    "di verifica e ogni obiettivo che richiede un controllo nell'ambiente resta incompiuto.",
  request_user_action:
    "Sospende il run in attesa di una risposta umana. Richiede sempre l'utente, anche in " +
    "modalità autonoma.",
};

function ToolCard({ tool }: { tool: ToolDescriptor }) {
  const [open, setOpen] = useState(false);
  const caveat = CAVEATS[tool.name];

  return (
    <article className="rounded-xl border border-border bg-surface">
      <button
        type="button"
        className="flex w-full items-start gap-3 px-5 py-4 text-left hover:bg-surface-raised/40"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown size={16} className="mt-0.5 shrink-0 text-muted" />
        ) : (
          <ChevronRight size={16} className="mt-0.5 shrink-0 text-muted" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <code className="font-mono text-sm font-medium text-foreground">{tool.name}</code>
            <span className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs text-muted">
              {tool.origin.startsWith("mcp:") ? <Plug size={10} /> : <Wrench size={10} />}
              {ORIGIN_LABELS[tool.origin] ?? tool.origin}
            </span>
            <span className="text-xs text-muted">
              {tool.arguments.length}{" "}
              {tool.arguments.length === 1 ? "argomento" : "argomenti"}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-sm text-muted">{tool.summary}</p>
        </div>
      </button>

      {open ? (
        <div className="space-y-4 border-t border-border px-5 py-4">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
            {tool.description}
          </p>

          {caveat ? (
            <p className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <span>{caveat}</span>
            </p>
          ) : null}

          {tool.arguments.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[32rem] text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-muted">
                    <th className="py-2 pr-4 font-medium">Argomento</th>
                    <th className="py-2 pr-4 font-medium">Tipo</th>
                    <th className="py-2 pr-4 font-medium">Obbligatorio</th>
                    <th className="py-2 font-medium">Descrizione</th>
                  </tr>
                </thead>
                <tbody>
                  {tool.arguments.map((argument) => (
                    <tr key={argument.name} className="border-b border-border last:border-b-0">
                      <td className="py-2 pr-4 align-top font-mono text-xs">{argument.name}</td>
                      <td className="py-2 pr-4 align-top font-mono text-xs text-muted">
                        {argument.type}
                      </td>
                      <td className="py-2 pr-4 align-top text-xs text-muted">
                        {argument.required ? "sì" : "no"}
                      </td>
                      <td className="py-2 align-top text-xs text-muted">
                        {argument.description || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-muted">Nessun argomento.</p>
          )}
        </div>
      ) : null}
    </article>
  );
}

export function ToolsView() {
  const [tools, setTools] = useState<ToolDescriptor[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setTools(await listTools());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Caricamento tool fallito");
    }
  }, []);

  useEffect(() => {
    refresh().catch(() => undefined);
  }, [refresh]);

  const builtIn = tools.filter((tool) => !tool.origin.startsWith("mcp:"));
  const external = tools.filter((tool) => tool.origin.startsWith("mcp:"));

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
      <header>
        <h2 className="text-lg font-semibold">Tools</h2>
        <p className="mt-1 text-sm text-muted">
          I {tools.length} tool che l'agente riceve in questa configurazione, con i loro
          argomenti. Non sono attivabili da qui: l'insieme dipende dalle impostazioni del
          backend (ricerca web, browser, server MCP) e cambia solo al riavvio.
        </p>
      </header>

      {error ? (
        <p className="rounded-lg border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {tools.length === 0 && !error ? <PanelEmpty>Nessun tool.</PanelEmpty> : null}

      {builtIn.length ? (
        <div className="space-y-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted">
            Interni all'harness
          </h3>
          {builtIn.map((tool) => (
            <ToolCard key={tool.name} tool={tool} />
          ))}
        </div>
      ) : null}

      {external.length ? (
        <div className="space-y-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted">
            Da server MCP
          </h3>
          {external.map((tool) => (
            <ToolCard key={tool.name} tool={tool} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
