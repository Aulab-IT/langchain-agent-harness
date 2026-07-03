"""Step 08: memoria sempre caricata e skills disponibili su richiesta."""

from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI

from steps._shared import require_api_key


def main() -> None:
    root = Path.cwd().resolve()
    agent = create_deep_agent(
        model=ChatOpenAI(
            model="gpt-5.4-mini",
            api_key=require_api_key(),
            use_responses_api=True,
            store=False,
        ),
        backend=FilesystemBackend(root_dir=root, virtual_mode=True),
        memory=["/memories/AGENTS.md"],
        skills=["/skills/"],
        system_prompt="Usa memoria e skills senza salvare segreti.",
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Quali preferenze operative ricordi?"}]}
    )
    print(result["messages"][-1].text)


if __name__ == "__main__":
    main()

