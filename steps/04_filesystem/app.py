"""Step 04: filesystem come memoria operativa e superficie di collaborazione."""

from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI

from steps._shared import require_api_key


def main() -> None:
    root = Path("workspace").resolve()
    root.mkdir(exist_ok=True)
    model = ChatOpenAI(
        model="gpt-5.4-mini",
        api_key=require_api_key(),
        use_responses_api=True,
        store=False,
    )
    agent = create_deep_agent(
        model=model,
        backend=FilesystemBackend(root_dir=root, virtual_mode=True),
        system_prompt="Lavora nei file. Scrivi sempre un piano prima dell'artefatto finale.",
    )
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Crea /plan.md e poi /saluto.txt. Verifica rileggendo entrambi.",
                }
            ]
        }
    )
    print(result["messages"][-1].text)


if __name__ == "__main__":
    main()

