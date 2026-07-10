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

export const SESSION_OVERRIDE_LABELS: Record<ModelOverride, string> = {
  auto: "Sessione: modello automatico",
  default: "Sessione: sempre modello base",
  strong: "Sessione: sempre modello forte",
};

const CHOICE_NAMES: Record<Exclude<MessageModel, "auto">, string> = {
  strong: "forte",
  default: "base",
};

/**
 * Cosa mostrare sul controllo per-messaggio. Quando la sessione è forzata su un modello e il
 * messaggio non lo scavalca, dire «automatico» sarebbe falso: il router non sta decidendo
 * niente. Il controllo dichiara da chi eredita.
 */
export function messageModelLabel(
  messageModel: MessageModel,
  sessionModel: ModelOverride,
): string {
  if (messageModel !== "auto") {
    return `Questo messaggio: ${CHOICE_NAMES[messageModel]}`;
  }
  if (sessionModel !== "auto") {
    return `Dalla sessione: ${CHOICE_NAMES[sessionModel]}`;
  }
  return "Questo messaggio: automatico";
}

export function messageModelTitle(
  messageModel: MessageModel,
  sessionModel: ModelOverride,
): string {
  if (messageModel !== "auto") {
    return (
      `Aggiunge ${MARKERS[messageModel]} in fondo al messaggio, in chiaro. ` +
      "Vale solo per questo invio e scavalca l'impostazione di sessione."
    );
  }
  if (sessionModel !== "auto") {
    return (
      `L'intera sessione è forzata sul modello ${CHOICE_NAMES[sessionModel]}. ` +
      "Clicca per scavalcare la scelta solo su questo messaggio."
    );
  }
  return (
    "Il router sceglie il modello dal contenuto della richiesta. " +
    "Clicca per forzarlo su questo messaggio."
  );
}
