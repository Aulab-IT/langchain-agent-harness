"""Step 01: una semplice conversazione conservata in memoria."""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from steps._shared import require_api_key


def run_chat() -> None:
    api_key = require_api_key()
    model = ChatOpenAI(
        model="gpt-5.4-mini",
        api_key=api_key,
        reasoning_effort="low",
        use_responses_api=True,
        store=False,
    )
    messages: list[BaseMessage] = [
        SystemMessage("Rispondi in italiano e in modo conciso.")
    ]
    while True:
        text = input("tu> ").strip()
        if text in {"/exit", "/quit"}:
            break
        messages.append(HumanMessage(text))
        response = model.invoke(messages)
        messages.append(response)
        if isinstance(response, AIMessage):
            print(f"agente> {response.text}")


if __name__ == "__main__":
    run_chat()

