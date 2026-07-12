/* eslint-disable react-refresh/only-export-components -- provider e hook convivono per convenzione */
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { getNotifications, markNotificationsRead, type AppNotification } from "../../api";
import { iconFor } from "../../lib/notifications";

const POLL_MS = 6_000;
const TOAST_MS = 6_000;

type NotificationsValue = {
  items: AppNotification[];
  unread: number;
  markAllRead: () => void;
  toasts: AppNotification[];
  dismissToast: (id: number) => void;
};

const NotificationsCtx = createContext<NotificationsValue | null>(null);

export function useNotifications(): NotificationsValue {
  const value = useContext(NotificationsCtx);
  if (value === null) throw new Error("useNotifications fuori da NotificationsProvider");
  return value;
}

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [toasts, setToasts] = useState<AppNotification[]>([]);
  const lastSeenId = useRef(0);
  const seeded = useRef(false);
  const notifyGranted = useRef(false);
  const timers = useRef<Map<number, number>>(new Map());

  function dismissToast(id: number) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  }

  useEffect(() => {
    if ("Notification" in window) {
      if (Notification.permission === "granted") {
        notifyGranted.current = true;
      } else if (Notification.permission !== "denied") {
        void Notification.requestPermission().then((p) => {
          notifyGranted.current = p === "granted";
        });
      }
    }

    const handleFresh = (fresh: AppNotification[]) => {
      // Toast in-app: appare in ogni tab, senza dipendere dal permesso desktop. Utile per la
      // tab affiancata ma non a fuoco, dove il popup di sistema non sempre arriva o è bloccato.
      const unfocused = !document.hasFocus();
      for (const n of fresh) {
        if (n.id <= lastSeenId.current) continue;
        setToasts((prev) => (prev.some((t) => t.id === n.id) ? prev : [...prev, n]));
        const timer = window.setTimeout(() => dismissToast(n.id), TOAST_MS);
        timers.current.set(n.id, timer);
        // Popup desktop solo se la tab non ha il focus ed è stato concesso il permesso.
        if (notifyGranted.current && unfocused) {
          try {
            new Notification(`${iconFor(n.type)} Harness`, { body: n.title, tag: String(n.id) });
          } catch {
            // Notifiche di sistema non disponibili: resta il toast in-app.
          }
        }
      }
    };

    const refresh = () => {
      getNotifications()
        .then((data) => {
          if (seeded.current) {
            handleFresh(data.notifications);
          } else {
            seeded.current = true;
          }
          lastSeenId.current = data.notifications.reduce(
            (m, n) => Math.max(m, n.id),
            lastSeenId.current,
          );
          setItems(data.notifications);
          setUnread(data.unread_count);
        })
        .catch(() => undefined);
    };

    refresh();
    const poll = window.setInterval(refresh, POLL_MS);
    const activeTimers = timers.current;
    return () => {
      window.clearInterval(poll);
      activeTimers.forEach((t) => window.clearTimeout(t));
      activeTimers.clear();
    };
  }, []);

  function markAllRead() {
    markNotificationsRead(null)
      .then((r) => setUnread(r.unread_count))
      .then(() => setItems((prev) => prev.map((n) => ({ ...n, read: true }))))
      .catch(() => undefined);
  }

  return (
    <NotificationsCtx.Provider value={{ items, unread, markAllRead, toasts, dismissToast }}>
      {children}
    </NotificationsCtx.Provider>
  );
}
