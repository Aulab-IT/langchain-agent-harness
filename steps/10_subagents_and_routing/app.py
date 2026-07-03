"""Step 10: delegazione con contesto isolato e routing del modello."""

from collections.abc import Callable

from deepagents import create_deep_agent
from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_openai import ChatOpenAI

from steps._shared import require_api_key


def main() -> None:
    key = require_api_key()
    fast = ChatOpenAI(model="gpt-5.4-mini", api_key=key, use_responses_api=True, store=False)
    strong = ChatOpenAI(model="gpt-5.5", api_key=key, use_responses_api=True, store=False)

    @wrap_model_call
    def route(
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        selected = strong if len(request.messages) > 20 else fast
        return handler(request.override(model=selected))

    agent = create_deep_agent(
        model=fast,
        middleware=[route],
        subagents=[
            {
                "name": "reviewer",
                "description": "Controlla in modo indipendente una soluzione complessa.",
                "system_prompt": "Cerca omissioni e restituisci problemi concreti.",
                "tools": [],
                "model": strong,
            }
        ],
        system_prompt="Delega al revisore quando serve un controllo indipendente.",
    )
    print(agent)


if __name__ == "__main__":
    main()

