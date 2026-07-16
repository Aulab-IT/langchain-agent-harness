"""Step 15: budget del contesto, offload e ledger hard per il run."""

from decimal import Decimal

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent_harness.context_budget import ContextBudget, ContextBudgetManager, offload_tool_output
from agent_harness.run_budget import BudgetRate, RunBudgetLimits, RunBudgetTracker


def main() -> None:
    manager = ContextBudgetManager(tool_output_soft_limit=100)
    context = ContextBudget(max_tokens=1_000, reserved_output_tokens=200)
    messages = [
        SystemMessage(content="Regole " * 50),
        ToolMessage(content="x" * 2_000, tool_call_id="c1"),
    ]
    snapshot = manager.inspect(messages, context)
    print("Contesto:", snapshot.total_tokens, "token; azione:", manager.decide(snapshot, context))
    print(offload_tool_output("x" * 2_000, reference="/workspace/tool-output.txt").render())

    limits = RunBudgetLimits(
        max_tokens=10_000,
        max_cost_usd=Decimal("0.10"),
        max_seconds=60,
        max_model_calls=4,
        max_subagent_calls=2,
        max_subagent_model_calls=2,
        max_subagent_tokens=4_000,
        reserved_output_tokens=1_000,
    )
    tracker = RunBudgetTracker(limits)
    rate = BudgetRate.from_values("openai", "demo", "1", "6", tier="low")
    reservation = tracker.before_model_call(
        kind="root", rate=rate, estimated_input_tokens=800, reserved_output_tokens=500
    )
    final = tracker.complete_model_call(
        reservation,
        [
            AIMessage(
                content="ok",
                usage_metadata={
                    "input_tokens": 800,
                    "output_tokens": 120,
                    "total_tokens": 920,
                },
            )
        ],
    )
    print("Run:", final.total_tokens, "token; costo $", final.cost_usd)


if __name__ == "__main__":
    main()
