import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/**
 * Tooltip su hover **e su focus**: chi naviga da tastiera non passa mai il mouse sopra un
 * elemento, e un contenuto raggiungibile solo col puntatore è un contenuto che non esiste.
 *
 * Si chiude con Escape, come ogni cosa che compare sopra il resto della pagina.
 */
export function Tooltip({
  content,
  children,
  className = "",
}: {
  content: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <span
      ref={ref}
      className={`relative inline-flex ${className}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <span aria-describedby={open ? id : undefined} className="inline-flex">
        {children}
      </span>
      {open ? (
        <span
          id={id}
          role="tooltip"
          className="pointer-events-none absolute bottom-full left-0 z-30 mb-2 w-72 rounded-xl border border-border bg-surface p-3 text-left shadow-2xl"
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}
