// Icone e categorie delle notifiche, in un modulo a parte così i componenti che le usano
// restano puri (fast-refresh) e la mappa è condivisa senza duplicazioni.
export const NEEDS_YOU = new Set(["needs_approval", "needs_action"]);

export function iconFor(type: string): string {
  if (type === "run_completed") return "✅";
  if (type === "run_failed") return "❌";
  if (type === "run_incomplete") return "⚠️";
  if (NEEDS_YOU.has(type)) return "🙋";
  return "•";
}
