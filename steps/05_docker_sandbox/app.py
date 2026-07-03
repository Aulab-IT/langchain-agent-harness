"""Step 05: esecuzione di codice in un container Docker effimero."""

from pathlib import Path

from agent_harness.sandbox import DockerSandbox


def main() -> None:
    workspace = Path("workspace")
    workspace.mkdir(exist_ok=True)
    sandbox = DockerSandbox(workspace.resolve())
    print(sandbox.execute("python --version && printf 'sandbox ok\\n' > proof.txt"))


if __name__ == "__main__":
    main()

