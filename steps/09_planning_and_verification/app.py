"""Step 09: piano esplicito e verifica riproducibile nel sandbox."""

from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI

from agent_harness.sandbox import DockerSandbox
from steps._shared import require_api_key


def main() -> None:
    root = Path("workspace").resolve()
    root.mkdir(exist_ok=True)
    verify_tool = DockerSandbox(root).as_tool()
    agent = create_deep_agent(
        model=ChatOpenAI(
            model="gpt-5.4-mini",
            api_key=require_api_key(),
            use_responses_api=True,
            store=False,
        ),
        tools=[verify_tool],
        backend=FilesystemBackend(root_dir=root, virtual_mode=True),
        system_prompt=(
            "Per compiti articolati usa write_todos e /plan.md. "
            "Prima di concludere esegui una verifica con docker_exec."
        ),
    )
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Crea numbers.py che stampa la somma da 1 a 100 e verificalo.",
                }
            ]
        }
    )
    print(result["messages"][-1].text)


if __name__ == "__main__":
    main()

