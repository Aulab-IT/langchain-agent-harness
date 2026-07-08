import { memo } from "react";
import { fileDownloadUrl } from "../../api";
import { timeLabel } from "../../lib/format";
import type { Message } from "../../types";
import { FileIcon } from "../shared/FileIcon";
import { MarkdownContent } from "./MarkdownContent";

export const ChatMessage = memo(function ChatMessage({
  message,
  model,
  sessionId,
}: {
  message: Message;
  model: string;
  sessionId: string;
}) {
  const isAgent = message.role === "assistant";
  return (
    <article className={`flex gap-3 ${isAgent ? "" : "flex-row-reverse"}`}>
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold ${
          isAgent
            ? "border border-accent/20 bg-accent/10 text-accent"
            : "border border-border bg-surface-raised text-muted"
        }`}
      >
        {isAgent ? "✦" : "N"}
      </div>
      <div className={`min-w-0 max-w-[85%] ${isAgent ? "" : "text-right"}`}>
        <div
          className={`mb-1.5 flex flex-wrap items-center gap-2 ${isAgent ? "" : "justify-end"}`}
        >
          <strong className="text-sm">{isAgent ? "Agente" : "Tu"}</strong>
          {isAgent ? (
            <span className="rounded-full border border-border px-2 py-0.5 font-mono text-xs text-muted">
              {model}
            </span>
          ) : null}
          <time className="text-xs text-muted">{timeLabel(message.created_at)}</time>
        </div>
        <div
          className={`rounded-xl border px-4 py-3 text-base leading-relaxed ${
            isAgent
              ? "border-border bg-surface-raised text-foreground"
              : "border-accent/20 bg-accent/5 text-foreground"
          }`}
        >
          <MarkdownContent content={message.content} sessionId={sessionId} />
        </div>
        {message.attachments?.length ? (
          <div className={`mt-2 flex flex-wrap gap-2 ${isAgent ? "" : "justify-end"}`}>
            {message.attachments.map((name) => (
              <a
                key={name}
                className="inline-flex max-w-[200px] items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm hover:bg-surface-raised"
                href={fileDownloadUrl(sessionId, name)}
                download
                title={name}
              >
                <FileIcon type={name.split(".").pop()?.toUpperCase() ?? ""} />
                <span className="truncate">{name}</span>
              </a>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
});
