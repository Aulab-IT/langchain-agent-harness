"""Misura se il grader distingue le risposte buone dalle cattive.

Il grader è un modello che giudica un modello. L'unico modo di sapere se serve a qualcosa è
dargli in pasto risposte di cui conosciamo già l'esito e guardare che voti dà. Il corpus in
`grader_calibration.json` contiene risposte **reali**, raccolte dai run: comprese quelle cattive,
che l'agente dopo il fix del prompt non produce più e che quindi vanno conservate qui.

Criterio di accettazione, e non è negoziabile:

    max(voto delle cattive) < min(voto delle buone)

Se le due nuvole si sovrappongono, nessuna soglia le separa, e il grader non può fare da cancello.

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
from agent_harness.factory import _openai_model, tier_spec  # noqa: E402
from agent_harness.verification import RubricGrader  # noqa: E402

CORPUS = Path(__file__).parent / "grader_calibration.json"


async def main(repeat: int) -> int:
    settings = Settings()
    # Lo stesso gradino che usa il grader in produzione (vedi `factory.build_harness`).
    spec = tier_spec(settings, "mid")
    model = _openai_model(spec.name, settings.require_openai_key(), reasoning_effort=spec.effort)
    grader = RubricGrader.from_chat_model(model, threshold=settings.harness_rubric_threshold)

    campioni = json.loads(CORPUS.read_text(encoding="utf-8"))
    print(f"corpus: {len(campioni)} risposte · grader: {spec.name} · giri: {repeat}")
    print(f"soglia: {settings.harness_rubric_threshold}\n")

    voti: dict[str, list[float]] = {}
    vetoed: dict[str, int] = {}
    for giro in range(repeat):
        for campione in campioni:
            risultato = await grader.grade(campione["goal"], campione["answer"])
            voti.setdefault(campione["id"], []).append(risultato.score)
            if risultato.safety_vetoed:
                vetoed[campione["id"]] = vetoed.get(campione["id"], 0) + 1
        print(f"  giro {giro + 1}/{repeat} completato")

    print(f"\n{'esito':10s} {'caso':32s} {'voto':>6s}  {'passa?':>7s}  veto")
    print("-" * 72)
    buone: list[float] = []
    cattive: list[float] = []
    for campione in sorted(campioni, key=lambda c: c["label"]):
        cid = campione["id"]
        media = st.mean(voti[cid])
        (cattive if campione["label"] == "cattiva" else buone).append(media)
        passa = "sì" if media >= settings.harness_rubric_threshold else "no"
        print(
            f"{campione['label']:10s} {cid:32s} {media:6.2f}  {passa:>7s}"
            f"  {'×' + str(vetoed[cid]) if cid in vetoed else ''}"
        )

    print(f"\nbuone : min {min(buone):.2f}  media {st.mean(buone):.2f}  max {max(buone):.2f}")
    print(f"cattive: min {min(cattive):.2f}  media {st.mean(cattive):.2f}  max {max(cattive):.2f}")
    margine = min(buone) - max(cattive)
    separato = margine > 0
    print(f"\nmargine di separazione: {margine:+.2f}")

    falsi_negativi = [c for c in cattive if c >= settings.harness_rubric_threshold]
    falsi_positivi = [b for b in buone if b < settings.harness_rubric_threshold]
    print(f"cattive che passerebbero la soglia : {len(falsi_negativi)}/{len(cattive)}")
    print(f"buone bocciate dalla soglia        : {len(falsi_positivi)}/{len(buone)}")

    if separato and not falsi_negativi:
        print("\n✓ il grader separa. Le cattive stanno tutte sotto le buone.")
        return 0
    print("\n✗ il grader NON separa: le due nuvole si sovrappongono.")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    raise SystemExit(asyncio.run(main(parser.parse_args().repeat)))
