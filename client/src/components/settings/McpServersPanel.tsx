import { AlertTriangle, Plug, RefreshCw, Save, ServerCog } from "lucide-react";
import { useEffect, useState } from "react";
import { getMcpConfig, getMcpStatus, updateMcpConfig } from "../../api";
import type { McpServerStatus } from "../../types";

const PLACEHOLDER = `{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "\${GITHUB_TOKEN}" }
    },
    "linear": { "url": "https://mcp.linear.app/sse", "transport": "sse" }
  }
}`;

export function McpServersPanel({ onSaved }: { onSaved: () => void }) {
  const [content, setContent] = useState("");
  const [servers, setServers] = useState<McpServerStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [probing, setProbing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function refreshStatus() {
    setProbing(true);
    getMcpStatus()
      .then((s) => setServers(s.servers))
      .catch(() => setServers([]))
      .finally(() => setProbing(false));
  }

  useEffect(() => {
    getMcpConfig()
      .then((c) => setContent(c.content))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
    refreshStatus();
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateMcpConfig(content);
      setContent(updated.content);
      setSaved(true);
      onSaved();
      refreshStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface">
      <div className="flex items-center gap-3 border-b border-border px-6 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-warning/20 bg-warning/10 text-warning">
          <ServerCog size={18} />
        </div>
        <div>
          <h2 className="text-lg font-semibold">Server MCP</h2>
          <p className="text-sm text-muted">
            Aggiungi server Model Context Protocol nel formato standard <code>mcpServers</code>.
            Valgono dal run successivo. I segreti si passano con <code>{"${VAR}"}</code>, espansi
            dall'ambiente: nel file resta il riferimento, non la chiave.
          </p>
        </div>
      </div>

      <div className="border-b border-border px-6 py-4">
        <div className="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 px-3 py-2 text-xs text-muted">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0 text-warning" />
          <span>
            I server stdio (<code>command</code>) girano <strong>sull'host</strong>, fuori dalla
            sandbox Docker dell'agente. Aggiungi solo server di cui ti fidi.
          </span>
        </div>
      </div>

      <div className="px-6 py-5">
        <label className="mb-2 block text-sm font-medium">Configurazione (JSON)</label>
        <textarea
          value={content}
          spellCheck={false}
          onChange={(e) => {
            setContent(e.target.value);
            setSaved(false);
          }}
          placeholder={loading ? "Caricamento…" : PLACEHOLDER}
          rows={12}
          className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs outline-none focus:border-warning/40"
        />
      </div>

      <div className="border-t border-border px-6 py-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Plug size={15} className="text-muted" /> Stato server
          </div>
          <button
            type="button"
            onClick={refreshStatus}
            disabled={probing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted transition hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw size={13} className={probing ? "animate-spin" : ""} /> Verifica
          </button>
        </div>
        {servers.length === 0 ? (
          <p className="text-xs text-muted">Nessun server rilevato.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {servers.map((s) => (
              <div
                key={s.name}
                className="flex flex-col gap-1 rounded-lg border border-border bg-background px-3 py-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-sm">
                    <span
                      className={`inline-block h-2 w-2 flex-shrink-0 rounded-full ${
                        s.connected ? "bg-success" : "bg-danger"
                      }`}
                    />
                    <code className="font-mono">{s.name}</code>
                    {s.builtin ? (
                      <span className="rounded bg-border/60 px-1.5 py-0.5 text-[10px] uppercase text-muted">
                        interno
                      </span>
                    ) : null}
                    <span className="text-xs text-muted">{s.transport}</span>
                  </span>
                  <span className="text-xs text-muted">
                    {s.connected ? `${s.tool_count} tool` : "non raggiungibile"}
                  </span>
                </div>
                {s.error ? <span className="text-xs text-danger">{s.error}</span> : null}
                {s.connected && s.tools.length ? (
                  <span className="font-mono text-[11px] text-muted">{s.tools.join(", ")}</span>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-border px-6 py-4">
        <div className="text-sm">
          {error ? (
            <span className="text-danger">{error}</span>
          ) : saved ? (
            <span className="text-success">Salvato. Attivo dal prossimo run.</span>
          ) : (
            <span className="text-muted">Un JSON non valido viene rifiutato e non salvato.</span>
          )}
        </div>
        <button
          type="button"
          onClick={save}
          disabled={saving || loading}
          className="inline-flex items-center gap-2 rounded-lg border border-warning/20 bg-warning/10 px-4 py-2 text-sm font-medium text-warning transition hover:bg-warning/20 disabled:opacity-50"
        >
          <Save size={15} /> {saving ? "Salvataggio…" : "Salva"}
        </button>
      </div>
    </div>
  );
}
