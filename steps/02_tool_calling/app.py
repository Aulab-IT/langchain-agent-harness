"""Step 02: ciclo ReAct gestito da create_agent."""

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI

from steps._shared import require_api_key


@tool
def multiply(a: float, b: float) -> float:
    """Moltiplica due numeri."""
    return a * b


def main() -> None:
    model = ChatOpenAI(
        model="gpt-5.4-mini",
        api_key=require_api_key(),
        use_responses_api=True,
        store=False,
    )
    agent = create_agent(
        model=model,
        tools=[multiply],
        system_prompt="Usa gli strumenti quando rendono il risultato verificabile.",
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Quanto fa 17.5 per 8?"}]}
    )
    print(result["messages"][-1].text)


if __name__ == "__main__":
    main()

