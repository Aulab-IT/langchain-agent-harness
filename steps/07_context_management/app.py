"""Step 07: compaction e offloading degli output grandi."""

from pathlib import Path

from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_openai import ChatOpenAI

from steps._shared import require_api_key


def main() -> None:
    model = ChatOpenAI(
        model="gpt-5.4-mini",
        api_key=require_api_key(),
        use_responses_api=True,
        store=False,
    )
    workspace = Path("workspace").resolve()
    workspace.mkdir(exist_ok=True)
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[
            FilesystemMiddleware(
                backend=FilesystemBackend(root_dir=workspace, virtual_mode=True),
                tool_token_limit_before_evict=4_000,
            ),
            SummarizationMiddleware(
                model=model,
                trigger=("messages", 12),
                keep=("messages", 6),
            ),
        ],
    )
    print(
        "Agente creato con compaction dopo 12 messaggi e offloading "
        "degli output superiori a 4.000 token."
    )
    print(agent)


if __name__ == "__main__":
    main()

