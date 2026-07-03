"""Step 11: approvazione umana e continuazione con budget."""

import asyncio
import uuid

import typer

from agent_harness.factory import build_harness
from agent_harness.runner import GoalRunner


async def approve(payload: dict[str, object]) -> bool:
    print("Operazione sensibile richiesta:", payload)
    return typer.confirm("Approvare?", default=False)


async def main() -> None:
    goal = "Crea hello.py, eseguilo nel sandbox e conserva la prova."
    async with build_harness() as harness:
        result = await GoalRunner(harness, approve).run(
            goal,
            thread_id=str(uuid.uuid4()),
        )
        print(result.text)
        print("Completato:", result.completed, "Iterazioni:", result.iterations)


if __name__ == "__main__":
    asyncio.run(main())

