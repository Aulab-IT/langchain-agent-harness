import { ArrowDownToLine, Trash2, Upload } from "lucide-react";
import { useRef } from "react";
import { fileDownloadUrl } from "../../api";
import { ACCEPTED_FILES } from "../../lib/constants";
import { formatFileSize } from "../../lib/format";
import type { SessionFile } from "../../types";
import { FileIcon } from "../shared/FileIcon";
import { PanelEmpty } from "../shared/PanelEmpty";

const FILE_COLORS = ["#facc15", "#34d399", "#60a5fa", "#f472b6"];

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
          <ul className="divide-y divide-border">
            {files.map((file, index) => (
              <li
                key={file.name}
                className="flex items-center gap-3 px-5 py-3 hover:bg-surface-raised/40"
              >
                <span style={{ color: FILE_COLORS[index % FILE_COLORS.length] }}>
                  <FileIcon type={file.type} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{file.name}</div>
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
        ) : (
          <PanelEmpty>Nessun file in questa conversazione.</PanelEmpty>
        )}
      </div>
    </div>
  );
}
