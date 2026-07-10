import type { ModelOverride } from "../types";

/**
 * Forzare il modello su un singolo messaggio aggiunge un marcatore in chiaro al testo, non un
 * campo nascosto della richiesta. Il router lo riconosce in `middleware.py::_MESSAGE_OVERRIDE`,
 * e l'utente vede in chat esattamente ciò che ha chiesto.
 */
export type MessageModel = "auto" | "default" | "strong";

const MARKERS: Record<Exclude<MessageModel, "auto">, string> = {
  strong: "[Modello: forte]",
  default: "[Modello: base]",
};

export function withModelMarker(message: string, choice: MessageModel): string {
  const clean = message.trim();
  if (choice === "auto") return clean;
  return `${clean} ${MARKERS[choice]}`;
}

export function modelMarker(choice: Exclude<MessageModel, "auto">): string {
  return MARKERS[choice];
}

export const SESSION_OVERRIDE_LABELS: Record<ModelOverride, string> = {
  auto: "Modello automatico",
  default: "Sempre modello base",
  strong: "Sempre modello forte",
};
