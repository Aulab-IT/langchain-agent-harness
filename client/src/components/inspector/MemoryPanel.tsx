import { AlertTriangle, ArrowUpFromLine, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getSessionMemory, promoteSessionMemory, putSessionMemory } from "../../api";

export function MemoryPanel({ sessionId }: { sessionId: string }) {
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tokens, setTokens] = useState(0);
  const [maxChars, setMaxChars] = useState(0);

  const load = useCallback(async () => {
    try {
      const memory = await getSessionMemory(sessionId);
      setContent(memory.content);
      setSaved(memory.content);
      setTokens(memory.tokens);
      setMaxChars(memory.max_chars);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Lettura memoria fallita");
    }
  }, [sessionId]);

  useEffect(() => {
    setNotice("");
    load().catch(() => undefined);
  }, [load]);

  const save = async () => {
    setBusy(true);
    setNotice("");
    try {
      const memory = await putSessionMemory(sessionId, content);
      setSaved(content);
      setTokens(memory.tokens);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Salvataggio fallito");
    } finally {
      setBusy(false);
    }
  };

  const promote = async () => {
    const confirmed = window.confirm(
      "Copiare questa memoria nel template globale?\n\n" +
        "Il template viene iniettato nel prompt di OGNI sessione futura. Promuovi solo " +
        "contenuto che hai letto: se l'agente ha scritto qui istruzioni prese da una pagina " +
        "web o da un file non fidato, le riceverebbero anche tutte le altre sessioni.",
    );
    if (!confirmed) return;
    setBusy(true);
    try {
      await promoteSessionMemory(sessionId);
      setNotice("Memoria promossa nel template globale.");
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Promozione fallita");
    } finally {
      setBusy(false);
    }
  };

  const dirty = content !== saved;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border px-5 py-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Memoria di sessione</h3>
          <span
            className={`rounded-lg border border-border bg-surface-raised px-2 py-0.5 font-mono text-[11px] ${
              maxChars > 0 && content.length > maxChars * 0.9 ? "text-warning" : "text-muted"
            }`}
            title={`Entra nel prompt a ogni run. Cap: ${maxChars.toLocaleString("it-IT")} caratteri.`}
          >
            ~{tokens.toLocaleString("it-IT")} token
          </span>
        </div>
        <p className="text-xs text-muted">
          <code className="font-mono">memories/AGENTS.md</code> — seminata una volta dal template
          globale, poi vive solo in questa conversazione. Entra nel prompt a ogni run.
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {error ? (
          <p className="mb-3 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="mb-3 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success">
            {notice}
          </p>
        ) : null}

        <textarea
          className="h-64 w-full resize-y rounded-lg border border-border bg-background p-3 font-mono text-xs leading-relaxed outline-none focus:border-muted"
          value={content}
          onChange={(event) => setContent(event.target.value)}
          spellCheck={false}
          aria-label="Memoria della sessione"
        />

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-on-accent hover:bg-accent-soft disabled:opacity-40"
            onClick={save}
            disabled={busy || !dirty}
          >
            <Save size={15} />
            Salva
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface-raised disabled:opacity-40"
            onClick={promote}
            disabled={busy || dirty || !content.trim()}
            title={
              dirty
                ? "Salva prima le modifiche."
                : "Copia questa memoria nel template globale, usato da tutte le sessioni future."
            }
          >
            <ArrowUpFromLine size={15} />
            Promuovi nel template globale
          </button>
        </div>

        <p className="mt-4 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            La promozione non avviene mai da sola. Il template globale entra nel prompt di ogni
            sessione futura: è un canale attraverso il quale una sessione può parlare a tutte le
            altre. Leggi il contenuto prima di promuoverlo.
          </span>
        </p>
      </div>
    </div>
  );
}
