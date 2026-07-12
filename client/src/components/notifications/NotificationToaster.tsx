import { X } from "lucide-react";
import { iconFor } from "../../lib/notifications";
import { useNotifications } from "./NotificationsContext";

// Toaster a livello di root (fuori dall'header con backdrop-blur, che intrappolerebbe il
// posizionamento fixed): i banner scivolano in alto a destra e si chiudono da soli.
export function NotificationToaster() {
  const { toasts, dismissToast } = useNotifications();
  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed right-4 top-16 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="pointer-events-auto flex items-start gap-2.5 rounded-xl border border-border bg-surface px-4 py-3 shadow-2xl"
          role="status"
        >
          <span className="mt-0.5 shrink-0">{iconFor(toast.type)}</span>
          <p className="min-w-0 flex-1 text-sm">{toast.title}</p>
          <button
            type="button"
            aria-label="Chiudi notifica"
            className="shrink-0 rounded p-0.5 text-muted hover:text-foreground"
            onClick={() => dismissToast(toast.id)}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
