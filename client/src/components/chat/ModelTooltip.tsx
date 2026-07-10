import {
  OVERRIDE_DOT,
  OVERRIDE_PURPOSE,
  modelOfTier,
  nextOverride,
  overrideLabel,
  overrideTitleLabel,
} from "../../lib/modelOverride";
import type { ModelOverride, RuntimeModel } from "../../types";

const euros = new Intl.NumberFormat("it-IT", { maximumFractionDigits: 2 });

export function ModelTooltip({
  override,
  models,
}: {
  override: ModelOverride;
  models: RuntimeModel[];
}) {
  const model = override === "auto" ? undefined : modelOfTier(models, override);
  const cheapest = modelOfTier(models, "low");
  // Il rapporto col gradino più economico è la cifra che serve per decidere: i dollari assoluti
  // dicono quanto costa un milione di token, che nessuno ha in mente mentre scrive un messaggio.
  const ratio =
    model && cheapest && cheapest.price_out > 0 ? model.price_out / cheapest.price_out : null;

  return (
    <span className="block text-xs">
      <span className="flex items-center gap-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${OVERRIDE_DOT[override]}`} />
        <strong className="text-sm text-foreground">{overrideTitleLabel(override)}</strong>
      </span>

      {model ? (
        <span className="mt-2 block">
          <span className="block font-mono text-foreground">
            {model.name} · reasoning {model.effort}
          </span>
          <span className="block text-muted">
            ${euros.format(model.price_in)} in · ${euros.format(model.price_out)} out per milione
            di token
            {ratio && ratio > 1 ? ` · ${euros.format(ratio)}× il gradino basso` : ""}
          </span>
        </span>
      ) : (
        <span className="mt-2 block text-muted">
          Nessun costo fisso: dipende da ciò che chiedi.
        </span>
      )}

      <span className="mt-2 block text-muted">{OVERRIDE_PURPOSE[override]}</span>

      <span className="mt-2 block border-t border-border pt-2 text-muted">
        Click → {overrideLabel(nextOverride(override)).replace("Modello: ", "")}
      </span>
    </span>
  );
}
