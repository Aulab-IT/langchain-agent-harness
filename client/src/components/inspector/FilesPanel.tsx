import {
  ArrowDownToLine,
  ChevronRight,
  Folder,
  FolderOpen,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { fileDownloadUrl } from "../../api";
import { ACCEPTED_FILES } from "../../lib/constants";
import { formatFileSize } from "../../lib/format";
import type { SessionFile } from "../../types";
import { FileIcon } from "../shared/FileIcon";
import { PanelEmpty } from "../shared/PanelEmpty";

const FILE_COLORS = ["#facc15", "#34d399", "#60a5fa", "#f472b6"];

type FileGroup = { key: string; label: string; files: SessionFile[] };

function topFolder(name: string): string {
  const slash = name.indexOf("/");
  return slash === -1 ? "" : name.slice(0, slash);
}

// Nome mostrato dentro un gruppo: il percorso relativo alla cartella del gruppo, così i file
// annidati (es. work/ocr/page.png nel gruppo "work") restano leggibili come "ocr/page.png".
function relativeName(name: string, groupKey: string): string {
  return groupKey === "" ? name : name.slice(groupKey.length + 1);
}

// Ordine semantico del flusso di lavoro: prima gli input (radice: upload e script),
// poi il lavoro intermedio, infine i deliverable in output. Le altre cartelle stanno
// in mezzo, in ordine alfabetico.
function groupOrder(key: string): number {
  if (key === "") return 0;
  if (key === "work" || key === "working" || key === "tmp") return 1;
  if (key === "output" || key === "out" || key === "dist") return 3;
  return 2;
}

export function FilesPanel({
  sessionId,
  files,
  onUpload,
  onDelete,
}: {
  sessionId: string;
  files: SessionFile[];
  onUpload: (files: FileList | null) => void;
  onDelete: (name: string) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);

  const groups = useMemo<FileGroup[]>(() => {
    const map = new Map<string, SessionFile[]>();
    for (const file of files) {
      const key = topFolder(file.name);
      const bucket = map.get(key);
      if (bucket) bucket.push(file);
      else map.set(key, [file]);
    }
    return [...map.entries()]
      .map(([key, groupFiles]) => ({
        key,
        label: key === "" ? "(radice)" : key,
        files: groupFiles,
      }))
      .sort((a, b) => groupOrder(a.key) - groupOrder(b.key) || a.key.localeCompare(b.key));
  }, [files]);

  // Stato apertura delle cartelle. Persiste ai refresh (durante un run la lista file si
  // aggiorna in polling): non si azzera la scelta dell'utente. Le cartelle nuove partono
  // aperte solo se la sessione ha pochi file o c'è un'unica cartella.
  const [open, setOpen] = useState<Set<string>>(new Set());
  const known = useRef<Set<string>>(new Set());
  useEffect(() => {
    const compact = files.length <= 15 || groups.length === 1;
    const defaults: string[] = [];
    for (const group of groups) {
      if (!known.current.has(group.key)) {
        known.current.add(group.key);
        if (compact) defaults.push(group.key);
      }
    }
    if (defaults.length) setOpen((prev) => new Set([...prev, ...defaults]));
  }, [groups, files.length]);

  function toggle(key: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold">File conversazione</h3>
          <p className="text-xs text-muted">{files.length} file · isolati in questa sessione</p>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-on-accent hover:bg-accent-soft"
          onClick={() => fileRef.current?.click()}
        >
          <Upload size={15} />
          Carica
        </button>
        <input
          ref={fileRef}
          hidden
          multiple
          type="file"
          accept={ACCEPTED_FILES}
          onChange={(event) => onUpload(event.target.files)}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {files.length ? (
          <div className="divide-y divide-border">
            {groups.map((group) => {
              const isOpen = open.has(group.key);
              return (
                <section key={group.key}>
                  <button
                    type="button"
                    onClick={() => toggle(group.key)}
                    className="sticky top-0 z-10 flex w-full items-center gap-2 border-b border-border bg-surface px-4 py-2.5 text-left hover:bg-surface-raised/60"
                    aria-expanded={isOpen}
                  >
                    <ChevronRight
                      size={14}
                      className={`shrink-0 text-muted transition-transform ${
                        isOpen ? "rotate-90" : ""
                      }`}
                    />
                    {isOpen ? (
                      <FolderOpen size={15} className="shrink-0 text-accent" />
                    ) : (
                      <Folder size={15} className="shrink-0 text-muted" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">
                      {group.label}
                    </span>
                    <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted">
                      {group.files.length}
                    </span>
                  </button>
                  {isOpen ? (
                    <ul>
                      {group.files.map((file, index) => (
                        <li
                          key={file.name}
                          className="flex items-center gap-3 border-b border-border/60 px-5 py-2.5 pl-8 last:border-b-0 hover:bg-surface-raised/40"
                        >
                          <span style={{ color: FILE_COLORS[index % FILE_COLORS.length] }}>
                            <FileIcon type={file.type} />
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-medium" title={file.name}>
                              {relativeName(file.name, group.key)}
                            </div>
                            <div className="text-xs text-muted">{formatFileSize(file.size)}</div>
                          </div>
                          <a
                            className="rounded-lg p-2 text-muted hover:bg-surface-raised hover:text-foreground"
                            href={fileDownloadUrl(sessionId, file.name)}
                            download
                            aria-label={`Scarica ${file.name}`}
                          >
                            <ArrowDownToLine size={16} />
                          </a>
                          <button
                            type="button"
                            className="rounded-lg p-2 text-muted hover:bg-danger/10 hover:text-danger"
                            aria-label={`Elimina ${file.name}`}
                            onClick={() => onDelete(file.name)}
                          >
                            <Trash2 size={16} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </section>
              );
            })}
          </div>
        ) : (
          <PanelEmpty>Nessun file in questa conversazione.</PanelEmpty>
        )}
      </div>
    </div>
  );
}
