import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fileDownloadUrl } from "../../api";

// Il modello referenzia i file appena creati con un path relativo al workspace
// (es. "screenshot.png" o "/workspace/screenshot.png"): nel browser va tradotto
// nell'endpoint di download della sessione, altrimenti l'immagine risulta rotta.
function resolveWorkspaceSrc(src: string, sessionId?: string): string {
  if (!sessionId || /^(https?:|data:|blob:)/i.test(src)) return src;
  const relative = src.replace(/^\.?\/?(workspace\/)?/i, "");
  return fileDownloadUrl(sessionId, relative);
}

export function MarkdownContent({
  content,
  className = "",
  sessionId,
}: {
  content: string;
  className?: string;
  sessionId?: string;
}) {
  return (
    <div className={`markdown-body ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          img: ({ src, alt }) => (
            <img src={resolveWorkspaceSrc(String(src ?? ""), sessionId)} alt={alt ?? ""} />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
