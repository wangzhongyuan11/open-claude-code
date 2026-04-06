from pathlib import Path

from openagent.agent.profile import AgentProfile
from openagent.permission.models import PermissionRule
from openagent.permission.policy import SessionPermissionPolicy
from openagent.session.store import SessionStore
from openagent.skill import SkillManager


def _write_skill(root: Path, name: str, *, description: str = "Use for testing.", body: str = "# Test\nDo it.") -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\ncompatibility: [openagent]\nmetadata:\n  short-description: Test skill\n---\n{body}\n", encoding="utf-8")
    return path


def test_skill_manager_discovers_project_global_and_custom_skills(tmp_path: Path):
    workspace = tmp_path / "repo"
    home = tmp_path / "home"
    workspace.mkdir()
    _write_skill(workspace / ".opencode" / "skill", "project-skill")
    _write_skill(home / ".claude" / "skills", "global-skill")
    _write_skill(home / ".config" / "opencode" / "skills", "config-opencode-skill")
    _write_skill(tmp_path / "external", "external-skill")

    manager = SkillManager(workspace, extra_paths=[str(tmp_path / "external")], home=home)
    result = manager.refresh()

    assert [skill.name for skill in result.skills] == ["config-opencode-skill", "external-skill", "global-skill", "project-skill"]
    assert not result.errors
    loaded = manager.get("project-skill")
    assert loaded is not None
    assert loaded.info.scope == "project"
    assert "# Test" in loaded.content


def test_skill_manager_reports_invalid_names_missing_fields_and_duplicates(tmp_path: Path):
    workspace = tmp_path / "repo"
    home = tmp_path / "home"
    workspace.mkdir()
    _write_skill(workspace / ".opencode" / "skills", "dup-skill", description="Project copy")
    _write_skill(home / ".claude" / "skills", "dup-skill", description="Global copy")
    bad = workspace / ".opencode" / "skill" / "bad" / "SKILL.md"
    bad.parent.mkdir(parents=True)
    bad.write_text("---\nname: Bad Skill\ndescription: bad\n---\n# Bad\n", encoding="utf-8")
    missing = workspace / ".agents" / "skills" / "missing" / "SKILL.md"
    missing.parent.mkdir(parents=True)
    missing.write_text("---\nname: missing-desc\n---\n# Missing\n", encoding="utf-8")

    result = SkillManager(workspace, home=home).refresh()
    error_types = {error.type for error in result.errors}

    assert "duplicate_name" in error_types
    assert "invalid_name" in error_types
    assert "missing_required_field" in error_types
    assert [skill.name for skill in result.skills] == ["dup-skill"]


def test_skill_permission_can_deny_specific_skill(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    profile = AgentProfile(
        name="build",
        permission_rules=[PermissionRule(agent="build", permission="skill", pattern="blocked-skill", action="deny")],
    )
    policy = SessionPermissionPolicy(store, profile)

    assert policy.allows_skill(session.id, "openai-docs") is True
    assert policy.allows_skill(session.id, "blocked-skill") is False
