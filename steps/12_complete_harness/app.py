"""Step 12: avvio dell'harness completo."""

import asyncio
import uuid

from agent_harness.factory import build_harness
from agent_harness.runner import GoalRunner


async def reject_sensitive_actions(payload: dict[str, object]) -> bool:
    print("Demo non interattiva: operazione rifiutata.", payload)
    return False


async def main() -> None:
    async with build_harness() as harness:
        result = await GoalRunner(harness, reject_sensitive_actions).run(
            "Elenca gli strumenti disponibili e spiega quando useresti i subagenti.",
            thread_id=str(uuid.uuid4()),
        )
        print(result.text)


if __name__ == "__main__":
    asyncio.run(main())

