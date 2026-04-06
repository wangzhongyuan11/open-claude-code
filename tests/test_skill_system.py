from pathlib import Path

from openagent.agent.profile import AgentProfile
from openagent.agent.runtime import AgentRuntime
from openagent.permission.models import PermissionRule
from openagent.permission.policy import SessionPermissionPolicy
from openagent.config.settings import Settings
from openagent.domain.messages import AgentResponse
from openagent.providers.base import BaseProvider
from openagent.session.manager import SessionManager
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


def test_skill_manager_parses_multiline_frontmatter_lists(tmp_path: Path):
    workspace = tmp_path / "repo"
    home = tmp_path / "home"
    skill = workspace / ".opencode" / "skills" / "cloudflare" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: cloudflare\ndescription: Use for Cloudflare workers.\ncompatibility:\n  - workers\n  - durable-objects\n---\n# Cloudflare\n",
        encoding="utf-8",
    )

    result = SkillManager(workspace, home=home).refresh()

    assert not result.errors
    assert result.skills[0].compatibility == ["workers", "durable-objects"]


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


def test_runtime_exposes_skill_summaries_without_auto_injecting_bodies(tmp_path: Path):
    class PromptCaptureProvider(BaseProvider):
        def __init__(self):
            self.system_prompts: list[str] = []

        def generate(self, messages, tools, system_prompt=None):
            self.system_prompts.append(system_prompt or "")
            return AgentResponse(text="used skill")

    workspace = tmp_path / "repo"
    workspace.mkdir()
    _write_skill(workspace / ".opencode" / "skill", "skill-creator", description="Use when creating or updating a skill.")
    settings = Settings.from_workspace(workspace)
    store = SessionStore(settings.session_root)
    manager = SessionManager(store)
    session = manager.start(workspace=workspace)
    provider = PromptCaptureProvider()
    runtime = AgentRuntime(provider=provider, workspace=workspace, session_manager=manager, session=session, settings=settings)

    reply = runtime.run_turn("请只分析如何创建一个新的 skill，并说明 SKILL.md 规范，不要修改代码。")

    assert reply == "used skill"
    assert "skill-creator" in provider.system_prompts[-1]
    assert "Use when creating or updating a skill." in provider.system_prompts[-1]
    assert "<selected_skill" not in provider.system_prompts[-1]
    assert not any(part.type == "skill" for message in runtime.session.messages for part in message.parts)
