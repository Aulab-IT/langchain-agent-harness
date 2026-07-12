import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { fileDownloadUrl, getPreviewText, type PreviewText } from "../../api";
import { MarkdownContent } from "./MarkdownContent";

// Divide una riga CSV/TSV rispettando le virgolette doppie standard ("" = virgoletta letterale).
function splitRow(line: string, sep: string): string[] {
  const cells: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cur += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === sep) {
      cells.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  cells.push(cur);
  return cells;
}

function CsvTable({ content }: { content: string }) {
  const sep = content.includes("\t") && !content.includes(",") ? "\t" : ",";
  const rows = content
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((line) => line.length > 0)
    .slice(0, 500)
    .map((line) => splitRow(line, sep));
  if (!rows.length) return <p className="p-3 text-xs text-muted">File vuoto.</p>;
  const [header, ...body] = rows;
  return (
    <div className="max-h-96 overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 bg-surface-raised">
          <tr>
            {header.map((cell, i) => (
              <th
                key={i}
                className="border border-border px-2 py-1 text-left font-semibold text-foreground"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, r) => (
            <tr key={r} className="even:bg-surface-raised/40">
              {header.map((_, c) => (
                <td key={c} className="border border-border px-2 py-1 text-muted">
                  {row[c] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TextPreview({
  sessionId,
  name,
  onBroken,
}: {
  sessionId: string;
  name: string;
  onBroken: () => void;
}) {
  const [data, setData] = useState<PreviewText | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    getPreviewText(sessionId, name)
      .then((preview) => {
        if (alive) setData(preview);
      })
      .catch(() => {
        if (alive) onBroken();
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [sessionId, name, onBroken]);

  return (
    <figure className="w-full max-w-xl overflow-hidden rounded-lg border border-border bg-surface">
      <div className="min-h-[3rem]">
        {loading ? (
          <p className="p-3 text-xs text-muted">Caricamento anteprima…</p>
        ) : !data ? (
          <p className="p-3 text-xs text-muted">Anteprima non disponibile.</p>
        ) : data.kind === "markdown" ? (
          <div className="max-h-96 overflow-auto p-3">
            <MarkdownContent content={data.content} sessionId={sessionId} />
          </div>
        ) : data.kind === "csv" ? (
          <CsvTable content={data.content} />
        ) : (
          <pre className="max-h-96 overflow-auto p-3 font-mono text-xs leading-relaxed text-foreground">
            {data.content}
          </pre>
        )}
      </div>
      <figcaption className="flex items-center justify-between gap-2 border-t border-border px-3 py-2 text-xs">
        <span className="truncate text-muted" title={name}>
          {name}
          {data?.truncated ? " · anteprima troncata" : ""}
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
