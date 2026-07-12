import { Download, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { fileDownloadUrl, filePreviewUrl } from "../../api";
import { FileIcon } from "../shared/FileIcon";
import { TextPreview } from "./TextPreview";

// Deve corrispondere a `INLINE_MEDIA_TYPES` in `server.py`. Ciò che non è qui viene servito
// solo come allegato: `svg` e `html` sono documenti che eseguono script, e renderli inline
// sull'origine dell'API significherebbe farli girare con i privilegi dell'API stessa.
const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp"]);
// Deve corrispondere a `TEXT_PREVIEW_KINDS` in `server.py`. File di testo inerti, resi come
// testo/markdown/tabella dal contenuto JSON — mai serviti come documento eseguibile.
const TEXT_EXTENSIONS = new Set([
  "md",
  "markdown",
  "csv",
  "tsv",
  "txt",
  "log",
  "json",
  "yaml",
  "yml",
  "xml",
  "toml",
  "ini",
  "cfg",
  "py",
  "ts",
  "tsx",
  "js",
  "jsx",
  "sql",
  "sh",
]);

function extensionOf(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

function Lightbox({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6"
      role="dialog"
      aria-modal="true"
      aria-label={alt}
      onClick={onClose}
    >
      <button
        type="button"
        className="absolute right-5 top-5 rounded-lg p-2 text-white/80 hover:bg-white/10"
        aria-label="Chiudi anteprima"
        onClick={onClose}
      >
        <X size={20} />
      </button>
      <img
        src={src}
        alt={alt}
        className="max-h-full max-w-full rounded-lg object-contain"
        onClick={(event) => event.stopPropagation()}
      />
    </div>
  );
}

function DownloadCard({ sessionId, name }: { sessionId: string; name: string }) {
  return (
    <a
      className="inline-flex max-w-[220px] items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm hover:bg-surface-raised"
      href={fileDownloadUrl(sessionId, name)}
      download
      title={name}
    >
      <FileIcon type={extensionOf(name).toUpperCase()} />
      <span className="truncate">{name}</span>
      <Download size={13} className="shrink-0 text-muted" />
    </a>
  );
}

export function FilePreview({ sessionId, name }: { sessionId: string; name: string }) {
  const [open, setOpen] = useState(false);
  const [broken, setBroken] = useState(false);
  const extension = extensionOf(name);
  const source = filePreviewUrl(sessionId, name);
  const markBroken = useCallback(() => setBroken(true), []);

  if (IMAGE_EXTENSIONS.has(extension) && !broken) {
    return (
      <figure className="max-w-sm overflow-hidden rounded-lg border border-border bg-surface">
        <button type="button" onClick={() => setOpen(true)} className="block w-full">
          <img
            src={source}
            alt={name}
            loading="lazy"
            className="max-h-64 w-full object-contain"
            onError={() => setBroken(true)}
          />
        </button>
        <figcaption className="flex items-center justify-between gap-2 border-t border-border px-3 py-2 text-xs">
          <span className="truncate text-muted" title={name}>
            {name}
          </span>
          <a
            className="shrink-0 text-muted hover:text-foreground"
            href={fileDownloadUrl(sessionId, name)}
            download
            aria-label={`Scarica ${name}`}
          >
            <Download size={13} />
          </a>
        </figcaption>
        {open ? <Lightbox src={source} alt={name} onClose={() => setOpen(false)} /> : null}
      </figure>
    );
  }

  if (extension === "pdf" && !broken) {
    return (
      <figure className="w-full max-w-xl overflow-hidden rounded-lg border border-border bg-surface">
        {/* Niente `sandbox=""`: il sandbox vuoto fa rifiutare il visualizzatore PDF interno di
            Chromium/Edge, e non serve alla sicurezza — il server invia il file come
            `application/pdf` con `X-Content-Type-Options: nosniff`, quindi il browser lo rende
            sempre col proprio viewer (che confina l'eventuale JS del PDF), mai come HTML. */}
        <iframe
          src={source}
          title={name}
          className="h-96 w-full border-0 bg-background"
          onError={() => setBroken(true)}
        />
        <figcaption className="flex items-center justify-between gap-2 border-t border-border px-3 py-2 text-xs">
          <span className="truncate text-muted" title={name}>
            {name}
          </span>
          <a
            className="shrink-0 text-muted hover:text-foreground"
            href={fileDownloadUrl(sessionId, name)}
            download
            aria-label={`Scarica ${name}`}
          >
            <Download size={13} />
          </a>
        </figcaption>
      </figure>
    );
  }

  if (TEXT_EXTENSIONS.has(extension) && !broken) {
    return <TextPreview sessionId={sessionId} name={name} onBroken={markBroken} />;
  }

  return <DownloadCard sessionId={sessionId} name={name} />;
}
