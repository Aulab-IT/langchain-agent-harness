"""Misura se il grader distingue le risposte buone dalle cattive.

Il grader è un modello che giudica un modello. L'unico modo di sapere se serve a qualcosa è
dargli in pasto risposte di cui conosciamo già l'esito e guardare che voti dà. Il corpus in
`grader_calibration.json` contiene risposte **reali**, raccolte dai run: comprese quelle cattive,
che l'agente dopo il fix del prompt non produce più e che quindi vanno conservate qui.

Criterio di accettazione, e non è negoziabile:

    max(voto delle cattive) < min(voto delle buone)

Se le due nuvole si sovrappongono, nessuna soglia le separa, e il grader non può fare da cancello.

Le soglie sono due, perché le domande sono due.

`harness_rubric_threshold` (0.7) risponde a «l'obiettivo è raggiunto?». Sotto, l'agente riprova.
`harness_escalation_threshold` (0.5) risponde a «questo gradino ce la fa?». Sotto, il router
compra un modello più caro. La seconda dev'essere più esigente della prima: una risposta
appena sotto la sufficienza merita un secondo tentativo, non un modello che costa il doppio.

Uso:  uv run python evals/calibrate_grader.py [--repeat N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics as st
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)

from agent_harness.config import Settings  # noqa: E402
from agent_harness.factory import build_tier_models, tier_spec  # noqa: E402
from agent_harness.verification import RubricGrader  # noqa: E402

CORPUS = Path(__file__).parent / "grader_calibration.json"


async def main(repeat: int) -> int:
    settings = Settings()
    # Lo stesso gradino che usa il grader in produzione (`factory.build_harness`: grader_model =
    # tiers["mid"].model). Passa dal registry dei provider, quindi vale per OpenAI, Claude o un
    # provider locale — non più cablato su OpenAI come quando importava `_openai_model` (rimosso).
    spec = tier_spec(settings, "mid")
    model = build_tier_models(settings)["mid"].model
    grader = RubricGrader.from_chat_model(model, threshold=settings.harness_rubric_threshold)

    campioni = json.loads(CORPUS.read_text(encoding="utf-8"))
    uscita = settings.harness_rubric_threshold
    escalation = settings.harness_escalation_threshold
    print(f"corpus: {len(campioni)} risposte · grader: {spec.name} · giri: {repeat}")
    print(f"soglia di uscita: {uscita}   soglia di escalation: {escalation}\n")

    voti: dict[str, list[float]] = {}
    vetoed: dict[str, int] = {}
    for giro in range(repeat):
        for campione in campioni:
            risultato = await grader.grade(campione["goal"], campione["answer"])
            voti.setdefault(campione["id"], []).append(risultato.score)
            if risultato.safety_vetoed:
                vetoed[campione["id"]] = vetoed.get(campione["id"], 0) + 1
        print(f"  giro {giro + 1}/{repeat} completato")

    print(f"\n{'esito':10s} {'caso':32s} {'voto':>6s}  {'uscita':>7s}  {'sale?':>6s}  veto")
    print("-" * 80)
    buone: list[float] = []
    cattive: list[float] = []
    # Il peggiore dei giri, non la media: in produzione il cancello vede un campione solo.
    peggior_cattiva = 0.0
    for campione in sorted(campioni, key=lambda c: c["label"]):
        cid = campione["id"]
        media = st.mean(voti[cid])
        if campione["label"] == "cattiva":
            cattive.append(media)
            peggior_cattiva = max(peggior_cattiva, max(voti[cid]))
        else:
            buone.append(media)
        passa = "sì" if media >= uscita else "no"
        sale = "sì" if media < escalation else "no"
        print(
            f"{campione['label']:10s} {cid:32s} {media:6.2f}  {passa:>7s}  {sale:>6s}"
            f"  {'veto x' + str(vetoed[cid]) if cid in vetoed else ''}"
        )

    print(f"\nbuone : min {min(buone):.2f}  media {st.mean(buone):.2f}  max {max(buone):.2f}")
    print(f"cattive: min {min(cattive):.2f}  media {st.mean(cattive):.2f}  max {max(cattive):.2f}")
    print(f"cattiva peggiore in un singolo giro: {peggior_cattiva:.2f}")
    margine = min(buone) - max(cattive)
    separato = margine > 0
    print(f"\nmargine di separazione (medie): {margine:+.2f}")

    falsi_negativi = [c for c in cattive if c >= uscita]
    falsi_positivi = [b for b in buone if b < uscita]
    salite_inutili = [b for b in buone if b < escalation]
    print(f"cattive che passerebbero la soglia di uscita : {len(falsi_negativi)}/{len(cattive)}")
    print(f"buone bocciate dalla soglia di uscita        : {len(falsi_positivi)}/{len(buone)}")
    print(f"buone che farebbero salire il gradino        : {len(salite_inutili)}/{len(buone)}")

    problemi = []
    if not separato:
        problemi.append("le due nuvole si sovrappongono")
    if falsi_negativi:
        problemi.append("una risposta cattiva supera la soglia di uscita")
    if salite_inutili:
        problemi.append("una risposta buona farebbe salire il gradino")
    # Su un singolo giro, non sulla media: è così che il cancello lo incontra.
    if peggior_cattiva >= escalation and peggior_cattiva >= uscita:
        problemi.append("una risposta cattiva ha superato la soglia in almeno un giro")

    if not problemi:
        print("\n✓ il grader separa, e nessuna soglia cade dentro una delle due nuvole.")
        return 0
    print("\n✗ " + "; ".join(problemi))
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    raise SystemExit(asyncio.run(main(parser.parse_args().repeat)))
