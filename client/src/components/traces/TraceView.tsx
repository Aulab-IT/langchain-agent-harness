import { Activity } from "lucide-react";
import { timeLabel } from "../../lib/format";
import type { RunEvent } from "../../types";

export function TraceView({ events }: { events: RunEvent[] }) {
  return (
    <section className="mx-auto w-full max-w-4xl rounded-xl border border-border bg-surface">
      <div className="border-b border-border px-6 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-info/20 bg-info/10 text-info">
            <Activity size={18} />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Trace ultimo run</h2>
            <p className="text-sm text-muted">{events.length} eventi persistiti e replayabili</p>
          </div>
        </div>
      </div>
      <div className="max-h-[calc(100vh-220px)] overflow-y-auto p-4">
        {events.length ? (
          <div className="space-y-2">
            {events.map((event) => (
              <article
                key={event.id}
                className="grid gap-2 rounded-lg border border-border bg-surface-raised/30 px-4 py-3 sm:grid-cols-[auto_auto_1fr]"
              >
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-info" />
                <time className="font-mono text-xs text-muted">{timeLabel(event.created_at)}</time>
                <div className="min-w-0 sm:col-span-1">
                  <strong className="text-sm">{event.type}</strong>
                  <code className="mt-1 block overflow-x-auto font-mono text-xs text-muted">
                    {Object.keys(event.payload).length ? JSON.stringify(event.payload) : "—"}
                  </code>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 py-20 text-center">
            <Activity size={28} className="text-info" />
            <strong className="text-base">Nessun trace</strong>
            <span className="text-sm text-muted">Avvia un run nella sessione corrente.</span>
          </div>
        )}
      </div>
    </section>
  );
}
