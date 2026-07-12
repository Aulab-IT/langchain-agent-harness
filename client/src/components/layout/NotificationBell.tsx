import { Bell, Check } from "lucide-react";
import { useState } from "react";
import { relativeLabel } from "../../lib/format";
import { iconFor } from "../../lib/notifications";
import { useNotifications } from "../notifications/NotificationsContext";

export function NotificationBell() {
  const { items, unread, markAllRead } = useNotifications();
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          if (!open && unread) markAllRead();
        }}
        aria-label="Notifiche"
        className="relative rounded-lg border border-border p-1.5 text-muted hover:border-accent hover:text-foreground"
      >
        <Bell size={15} />
        {unread > 0 ? (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </button>

      {open ? (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-xl border border-border bg-surface shadow-2xl">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <span className="text-sm font-semibold">Notifiche</span>
              <button
                type="button"
                onClick={markAllRead}
                className="inline-flex items-center gap-1 text-xs text-muted hover:text-foreground"
              >
                <Check size={12} /> Segna lette
              </button>
            </div>
            <div className="max-h-96 overflow-y-auto">
              {items.length === 0 ? (
                <p className="px-4 py-6 text-center text-xs text-muted">Nessuna notifica.</p>
              ) : (
                items.map((n) => (
                  <div
                    key={n.id}
                    className={`flex items-start gap-2.5 border-b border-border px-4 py-2.5 text-sm ${
                      n.read ? "opacity-60" : ""
                    }`}
                  >
                    <span className="mt-0.5 shrink-0">{iconFor(n.type)}</span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate">{n.title}</p>
                      <p className="text-[11px] text-muted">{relativeLabel(n.created_at)}</p>
                    </div>
                    {!n.read ? (
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
