import type { ModelOverride, ModelTier, RuntimeModel } from "../types";

/**
 * C'è un solo controllo del modello, e vale per la sessione. Cambiarlo ha effetto dal messaggio
 * successivo e resta finché non lo si cambia di nuovo: è persistito in `sessions.model_override`.
 *
 * Il router riconosce ancora un marcatore `[Modello: …]` scritto a mano nel testo (vedi
 * `middleware.py::_MESSAGE_OVERRIDE`), perché quei marcatori sono già dentro i messaggi salvati.
 * Ma l'interfaccia non ne genera più: due controlli per la stessa dimensione erano uno di troppo.
 */
// L'ordine segue i colori, che seguono il costo: verde, giallo, rosso, poi si torna al router.
export const OVERRIDE_CYCLE: ModelOverride[] = ["low", "mid", "high", "auto"];

const TIER_NAMES: Record<ModelTier, string> = {
  low: "basso",
  mid: "medio",
  high: "alto",
};

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

export function nextOverride(current: ModelOverride): ModelOverride {
  const index = OVERRIDE_CYCLE.indexOf(current);
  return OVERRIDE_CYCLE[(index + 1) % OVERRIDE_CYCLE.length];
}

/**
 * Verde, giallo, rosso: il colore dice il costo, non la correttezza. Il rosso non segnala un
 * errore, segnala che quel gradino costa cinque volte il verde. Il testo del pulsante nomina
 * comunque il gradino, perché il colore da solo non è un'informazione accessibile.
 */
export const OVERRIDE_TONE: Record<ModelOverride, string> = {
  auto: "text-muted hover:bg-surface-raised hover:text-foreground",
  low: "text-success hover:bg-success/10",
  mid: "text-warning hover:bg-warning/10",
  high: "text-danger hover:bg-danger/10",
};

export function overrideLabel(override: ModelOverride): string {
  if (override === "auto") return "Modello: automatico";
  return `Modello: ${TIER_NAMES[override]}`;
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

/** A cosa serve ciascun gradino, nelle parole con cui il router lo sceglie. */
export const OVERRIDE_PURPOSE: Record<ModelOverride, string> = {
  auto: "Sceglie il router a ogni messaggio, e resta sul gradino basso finché la richiesta non chiede di salire.",
  low: "Richieste ordinarie: domande dirette, testi brevi, calcoli.",
  mid: "Lavoro sui file, verifiche nella sandbox, confronti fra fonti.",
  high: "Architettura, refactor, problemi dichiaratamente complessi.",
};

/** Il pallino colorato del tooltip, con lo stesso codice del pulsante. */
export const OVERRIDE_DOT: Record<ModelOverride, string> = {
  auto: "bg-muted",
  low: "bg-success",
  mid: "bg-warning",
  high: "bg-danger",
};

export function overrideTitleLabel(override: ModelOverride): string {
  return override === "auto" ? "Automatico" : `Gradino ${TIER_NAMES[override]}`;
}
