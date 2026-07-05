"""Step 13: loop engineering — verifica a rubric, trigger a eventi, hill climbing."""

import asyncio
from datetime import UTC, datetime

from agent_harness.config import Settings
from agent_harness.factory import build_strong_model
from agent_harness.improve import Proposal, build_report, propose, render_report
from agent_harness.triggers import cron_matches
from agent_harness.verification import RubricGrader


async def main() -> None:
    settings = Settings()
    strong_model = build_strong_model(settings)

    # Loop 2 — verifica a rubric della risposta finale.
    grader = RubricGrader.from_chat_model(strong_model, threshold=0.7)
    grade = await grader.grade(
        "Somma i numeri da 1 a 10 e mostra come hai verificato.",
        "La somma da 1 a 10 è 55, verificata con sum(range(1, 11)) == 55.",
    )
    print("Loop 2 verifica:", grade.passed, grade.score)

    # Loop 3 — un evento cron avvierebbe un run autonomo.
    now = datetime.now(UTC)
    print("Loop 3 cron '* * * * *' match:", cron_matches("* * * * *", now))

    # Loop 4 — dai trace a una proposta di miglioramento (propose-only).
    report = build_report(
        runs=[
            {
                "id": "demo-run",
                "status": "completed",
                "usage": {"total_tokens": 500},
            }
        ],
        events=[
            {
                "run_id": "demo-run",
                "type": "run.completed",
                "payload": {"completed": True},
            },
            {
                "run_id": "demo-run",
                "type": "tool.started",
                "payload": {"tool": "browser_read", "args": '{"url":"https://example.com"}'},
            },
            {
                "run_id": "demo-run",
                "type": "tool.failed",
                "payload": {"tool": "browser_read", "elapsed_ms": 50},
            },
        ],
    )
    proposal = await propose(
        render_report(report),
        strong_model.with_structured_output(Proposal),
    )
    print("Loop 4 sintesi:", proposal.summary)
    print("Loop 4 override proposti:", proposal.overrides)


if __name__ == "__main__":
    asyncio.run(main())
