from pathlib import Path

from langchain_core.messages import AIMessage

from agent_harness.outcome_checks import (
    SkillCatalogCompletionCheck,
    allows_existing_skill_outcome,
    requires_skill_catalog_change,
    skill_catalog_snapshot,
)
from agent_harness.skills import build_skill_md, write_skill


def test_skill_goal_requires_real_catalog_change(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    baseline = skill_catalog_snapshot(skills)
    check = SkillCatalogCompletionCheck(skills, baseline)

    assert requires_skill_catalog_change("Crea una nuova skill per i report")
    passed, feedback = check("Crea una nuova skill per i report", [])
    assert passed is False
    assert "skill_create" in feedback

    write_skill(
        skills,
        "report-maker",
        build_skill_md("report-maker", "Crea report verificati.", "# Procedura"),
    )
    assert check("Crea una nuova skill per i report", []) == (True, "")


def test_non_skill_goal_does_not_require_catalog_change(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    check = SkillCatalogCompletionCheck(skills, skill_catalog_snapshot(skills))

    assert check("Crea un report Markdown", []) == (True, "")


def test_conditional_skill_goal_accepts_only_inspected_valid_reuse(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    write_skill(
        skills,
        "pptx",
        build_skill_md("pptx", "Crea presentazioni PowerPoint.", "# Procedura"),
    )
    check = SkillCatalogCompletionCheck(skills, skill_catalog_snapshot(skills))
    goal = "Se non esiste una skill adeguata, crea una nuova skill per PowerPoint"
    marker = AIMessage(content="Adeguata. [SKILL_CATALOG_OUTCOME=reuse:pptx]")

    assert allows_existing_skill_outcome(goal)
    assert check(goal, [marker])[0] is False

    check.observe_event(
        {
            "type": "tool.completed",
            "tool": "skill_read",
            "output": '{"name": "pptx", "valid": true}',
        }
    )

    assert check(goal, [marker]) == (True, "")


def test_conditional_skill_goal_rejects_uninspected_or_unknown_reuse(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    check = SkillCatalogCompletionCheck(skills, skill_catalog_snapshot(skills))
    goal = "If no adequate skill exists, create a skill"

    check.observe_event(
        {
            "type": "tool.completed",
            "tool": "skill_read",
            "output": '{"name": "ghost", "valid": true}',
        }
    )

    passed, feedback = check(
        goal, [AIMessage(content="[SKILL_CATALOG_OUTCOME=reuse:ghost]")]
    )
    assert passed is False
    assert "condizionale" in feedback
