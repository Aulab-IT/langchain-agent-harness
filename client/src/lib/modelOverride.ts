import type { ModelOverride, ModelTier, RuntimeModel } from "../types";

/**
 * C'è un solo controllo del modello, e vale per la sessione. Cambiarlo ha effetto dal messaggio
 * successivo e resta finché non lo si cambia di nuovo: è persistito in `sessions.model_override`.
 *
 * Il router riconosce ancora un marcatore `[Modello: …]` scritto a mano nel testo (vedi
 * `middleware.py::_MESSAGE_OVERRIDE`), perché quei marcatori sono già dentro i messaggi salvati.
 * Ma l'interfaccia non ne genera più: due controlli per la stessa dimensione erano uno di troppo.
 */
export const OVERRIDE_CYCLE: ModelOverride[] = ["auto", "mid", "high", "low"];

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

export function overrideLabel(override: ModelOverride): string {
  if (override === "auto") return "Modello: automatico";
  return `Modello: ${TIER_NAMES[override]}`;
}

export function overrideTitle(override: ModelOverride, models: RuntimeModel[]): string {
  if (override === "auto") {
    return (
      "Il router sceglie il gradino dal contenuto della richiesta, e resta in basso finché " +
      "nulla dice di salire. Clicca per fissarlo per questa sessione."
    );
  }
  const model = modelOfTier(models, override);
  const name = model ? ` (${model.name}, reasoning ${model.effort})` : "";
  return (
    `Questa sessione usa il gradino ${TIER_NAMES[override]}${name} dal prossimo messaggio, ` +
    "finché non lo cambi. Clicca per passare al gradino successivo."
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
