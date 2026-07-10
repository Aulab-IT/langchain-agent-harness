import type { ModelOverride, ModelTier, RuntimeModel } from "../types";

/**
 * Forzare il gradino su un singolo messaggio aggiunge un marcatore in chiaro al testo, non un
 * campo nascosto della richiesta. Il router lo riconosce in `middleware.py::_MESSAGE_OVERRIDE`,
 * e l'utente vede in chat esattamente ciò che ha chiesto.
 */
export type MessageModel = "auto" | ModelTier;

export const TIER_ORDER: ModelTier[] = ["low", "mid", "high"];

const MARKERS: Record<ModelTier, string> = {
  low: "[Modello: basso]",
  mid: "[Modello: medio]",
  high: "[Modello: alto]",
};

const TIER_NAMES: Record<ModelTier, string> = {
  low: "basso",
  mid: "medio",
  high: "alto",
};

export function withModelMarker(message: string, choice: MessageModel): string {
  const clean = message.trim();
  if (choice === "auto") return clean;
  return `${clean} ${MARKERS[choice]}`;
}

/** Che gradino verrà usato quando nessun run ha ancora dichiarato la sua scelta. */
export function expectedTier(override: ModelOverride): {
  tier: ModelTier;
  source: "sessione" | "default";
} {
  if (override !== "auto") return { tier: override, source: "sessione" };
  return { tier: "low", source: "default" };
}

export function modelOfTier(models: RuntimeModel[], tier: ModelTier): RuntimeModel | undefined {
  return models.find((model) => model.tier === tier);
}

export const SESSION_OVERRIDE_LABELS: Record<ModelOverride, string> = {
  auto: "Sessione: gradino automatico",
  low: "Sessione: sempre gradino basso",
  mid: "Sessione: sempre gradino medio",
  high: "Sessione: sempre gradino alto",
};

/**
 * Cosa mostrare sul controllo per-messaggio. Quando la sessione è forzata su un gradino e il
 * messaggio non lo scavalca, dire «automatico» sarebbe falso: il router non sta decidendo
 * niente. Il controllo dichiara da chi eredita.
 */
export function messageModelLabel(
  messageModel: MessageModel,
  sessionModel: ModelOverride,
): string {
  if (messageModel !== "auto") return `Questo messaggio: ${TIER_NAMES[messageModel]}`;
  if (sessionModel !== "auto") return `Dalla sessione: ${TIER_NAMES[sessionModel]}`;
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
      `L'intera sessione è forzata sul gradino ${TIER_NAMES[sessionModel]}. ` +
      "Clicca per scavalcare la scelta solo su questo messaggio."
    );
  }
  return (
    "Il router sceglie il gradino dal contenuto della richiesta, e resta in basso " +
    "finché nulla dice di salire. Clicca per forzarlo su questo messaggio."
  );
}

/**
 * Etichetta del modello per navbar e barra di stato: il nome dichiarato dal router se un run è
 * in corso, altrimenti quello che sappiamo già che verrà usato, con la sua provenienza.
 */
export function modelLabel(
  models: RuntimeModel[],
  override: ModelOverride,
  live: string | null,
): string {
  if (live) return live;
  const { tier, source } = expectedTier(override);
  const model = modelOfTier(models, tier);
  return model ? `${model.name} (${source})` : "—";
}
