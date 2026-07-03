"""Step 03: checkpoint SQLite e thread conversazionali."""

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver

from steps._shared import require_api_key


def main() -> None:
    model = ChatOpenAI(
        model="gpt-5.4-mini",
        api_key=require_api_key(),
        use_responses_api=True,
        store=False,
    )
    config = {"configurable": {"thread_id": "lezione-03"}}
    with SqliteSaver.from_conn_string("state/step03.sqlite") as checkpointer:
        checkpointer.setup()
        agent = create_agent(model=model, tools=[], checkpointer=checkpointer)
        agent.invoke(
            {"messages": [{"role": "user", "content": "Ricorda il numero 314."}]},
            config=config,
        )
        result = agent.invoke(
            {"messages": [{"role": "user", "content": "Quale numero ricordi?"}]},
            config=config,
        )
        print(result["messages"][-1].text)


if __name__ == "__main__":
    main()

