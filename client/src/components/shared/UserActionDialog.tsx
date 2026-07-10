import { useRef, useState } from "react";
import { Check, ExternalLink, HandHelping, Loader2, Square, Upload } from "lucide-react";
import { uploadContextFile } from "../../api";
import { MarkdownContent } from "../chat/MarkdownContent";

type ResponseKind = "confirm" | "value" | "file";

export function UserActionDialog({
  runId,
  sessionId,
  payload,
  onSubmit,
  onCancel,
}: {
  runId: string;
  sessionId: string;
  payload: Record<string, unknown>;
  onSubmit: (body: { response?: string; cancel?: boolean }) => void;
  onCancel: () => void;
}) {
  const title = String(payload.title || "Azione richiesta");
  const instructions = String(payload.instructions || "");
  const url = typeof payload.url === "string" ? payload.url : "";
  const responseKind = (String(payload.response_kind || "confirm") as ResponseKind);
  const [value, setValue] = useState("");
  const [uploaded, setUploaded] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const handleFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    setUploadError("");
    try {
      for (const file of Array.from(files)) {
        const saved = await uploadContextFile(sessionId, file);
        setUploaded((current) => [...new Set([...current, saved.name])]);
      }
    } catch (reason) {
      setUploadError(reason instanceof Error ? reason.message : "Upload fallito");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const canSubmitValue =
    responseKind === "value"
      ? value.trim().length > 0
      : responseKind === "file"
        ? uploaded.length > 0
        : true;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      role="presentation"
    >
      <section
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-border bg-surface shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="user-action-title"
      >
        <div className="flex shrink-0 items-start gap-4 p-6 pb-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-accent/30 bg-accent/10 text-accent">
            <HandHelping size={22} />
          </div>
          <div>
            <h2 id="user-action-title" className="text-lg font-semibold">
              {title}
            </h2>
            <p className="mt-1 text-sm text-muted">
              Run {runId.slice(0, 8)} in pausa: serve un tuo intervento per sbloccare l'agente.
            </p>
          </div>
        </div>

        <div className="mx-6 min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-background p-4 text-sm">
          <MarkdownContent content={instructions} />
        </div>

        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="mx-6 mt-3 inline-flex items-center gap-2 self-start rounded-lg border border-accent/40 px-4 py-2 text-sm font-medium text-accent hover:bg-accent/10"
          >
            <ExternalLink size={15} /> Apri il link
          </a>
        ) : null}

        {responseKind === "value" ? (
          <div className="mx-6 mt-3">
            <label className="mb-1 block text-xs font-medium text-muted">
              Incolla qui il valore richiesto (codice, token, URL di redirect)
            </label>
            <textarea
              value={value}
              onChange={(event) => setValue(event.target.value)}
              rows={3}
              className="w-full resize-y rounded-lg border border-border bg-background p-3 font-mono text-sm outline-none focus:border-accent"
              placeholder="Es. 4/0Ab..."
            />
          </div>
        ) : null}

        {responseKind === "file" ? (
          <div className="mx-6 mt-3">
            <input
              ref={fileInput}
              type="file"
              multiple
              className="hidden"
              onChange={(event) => handleFiles(event.target.files)}
            />
            <button
              type="button"
              disabled={uploading}
              onClick={() => fileInput.current?.click()}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                void handleFiles(event.dataTransfer.files);
              }}
              className={`flex w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-sm transition-colors disabled:opacity-50 ${
                dragging
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border text-muted hover:border-accent/50 hover:text-accent"
              }`}
            >
              {uploading ? (
                <Loader2 size={20} className="animate-spin" />
              ) : (
                <Upload size={20} />
              )}
              <span className="font-medium">
                {uploading
                  ? "Caricamento…"
                  : "Trascina qui il file o clicca per sceglierlo"}
              </span>
              <span className="text-xs text-muted">Il file va nel workspace della sessione</span>
            </button>
            {uploaded.length > 0 ? (
              <p className="mt-2 text-sm text-success">Caricati: {uploaded.join(", ")}</p>
            ) : null}
            {uploadError ? <p className="mt-2 text-sm text-danger">{uploadError}</p> : null}
          </div>
        ) : null}

        <div className="flex shrink-0 flex-wrap items-center justify-end gap-3 p-6 pt-4">
          <button
            type="button"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-4 text-sm text-muted hover:bg-surface-raised"
            onClick={onCancel}
          >
            <Square size={10} fill="currentColor" /> Annulla
          </button>
          <button
            type="button"
            disabled={!canSubmitValue}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-on-accent hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => {
              if (responseKind === "value") onSubmit({ response: value.trim() });
              else if (responseKind === "file")
                onSubmit({ response: `File caricati nel workspace: ${uploaded.join(", ")}` });
              else onSubmit({ response: "" });
            }}
          >
            <Check size={15} /> {responseKind === "value" ? "Invia" : "Fatto"}
          </button>
        </div>
      </section>
    </div>
  );
}
