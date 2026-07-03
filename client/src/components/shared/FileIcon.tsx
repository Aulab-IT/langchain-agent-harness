import { File, FileCode2, FileText } from "lucide-react";

export function FileIcon({ type }: { type: string }) {
  if (["PY", "TS", "TSX", "JS", "JSON"].includes(type)) {
    return <FileCode2 size={18} className="shrink-0" />;
  }
  if (["MD", "TXT", "DOCX"].includes(type)) {
    return <FileText size={18} className="shrink-0" />;
  }
  return <File size={18} className="shrink-0" />;
}
