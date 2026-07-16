"""Step 17: piano di delegazione validato contro capacità e permessi reali."""

from agent_harness.subagent_routing import (
    DelegationPlan,
    RootToolRoute,
    RoutedTask,
    SubagentProfile,
    render_plan,
    validate_plan,
)


def main() -> None:
    profiles = [
        SubagentProfile(
            name="researcher",
            description="Ricerca fonti e restituisce note con provenienza.",
            capabilities=["research"],
            outputs=["source notes"],
            tools=["browser_read"],
            read_only=True,
        ),
        SubagentProfile(
            name="builder",
            description="Produce artefatti Python verificabili.",
            capabilities=["python"],
            outputs=["python artifact"],
            tools=["docker_exec"],
            read_only=False,
        ),
    ]
    proposed = DelegationPlan(
        delegate=True,
        rationale="Separare ricerca e costruzione.",
        root_tools=RootToolRoute(
            required=False,
            external_data_required=False,
            candidates=[],
            rationale="",
        ),
        tasks=[
            RoutedTask(
                id="build",
                objective="Crea un artefatto Python",
                selected_agent="researcher",
                alternatives=["builder"],
                reason="proposta da validare",
                depends_on=[],
                expected_output="python artifact",
                kind="work",
                required_tools=["docker_exec"],
                required_capabilities=["python"],
                requires_write=True,
                success_criteria=["test superati"],
            )
        ],
    )
    diagnostics: list[dict[str, object]] = []
    validated = validate_plan(proposed, profiles, diagnostics=diagnostics)
    print(render_plan(validated))
    print("Agente scelto:", validated.tasks[0].selected_agent)
    print("Diagnostica:", diagnostics)


if __name__ == "__main__":
    main()
