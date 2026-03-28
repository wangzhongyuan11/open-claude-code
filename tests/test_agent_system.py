from pathlib import Path

from openagent.agent.registry import build_agent_registry
from openagent.agent.runtime import AgentRuntime
from openagent.config.settings import Settings
from openagent.domain.messages import AgentResponse
from openagent.providers.base import BaseProvider
from openagent.session.manager import SessionManager
from openagent.session.store import SessionStore


class HiddenAwareProvider(BaseProvider):
    def generate(self, messages, tools, system_prompt=None):
        prompt = system_prompt or ""
        if "title generator" in prompt:
            return AgentResponse(text="Agent 系统测试")
        if "summarizing conversations" in prompt:
            return AgentResponse(text="Compact summary text")
        if "pull request description" in prompt:
            return AgentResponse(text="I added an agent registry and hidden agent prompts.")
        if "elite AI agent architect" in prompt:
            return AgentResponse(
                text='{"identifier":"ts-reviewer","whenToUse":"Use this agent when reviewing TypeScript code changes.","systemPrompt":"You are a TypeScript code review specialist."}'
            )
        return AgentResponse(text="ok")


def build_runtime(tmp_path: Path) -> AgentRuntime:
    settings = Settings.from_workspace(tmp_path)
    store = SessionStore(tmp_path / ".openagent" / "sessions")
    manager = SessionManager(store, max_messages_before_compact=3, prompt_recent_messages=2, prompt_max_tokens=200)
    session = manager.start(workspace=tmp_path)
    registry = build_agent_registry(settings)

    def provider_factory(profile=None):
        return HiddenAwareProvider()

    return AgentRuntime(
        provider=HiddenAwareProvider(),
        workspace=tmp_path,
        session_manager=manager,
        session=session,
        settings=settings,
        provider_factory=provider_factory,
        agent_registry=registry,
        agent_name="build",
    )


def test_agent_registry_lists_visible_agents(tmp_path: Path):
    settings = Settings.from_workspace(tmp_path)
    registry = build_agent_registry(settings)
    visible = [item.name for item in registry.list()]
    assert "build" in visible
    assert "plan" in visible
    assert "explore" in visible
    assert "title" not in visible
    assert registry.default_primary().name == "build"


def test_runtime_can_switch_to_plan_agent_and_filter_tools(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    message = runtime.switch_agent("plan")
    assert "plan" in message
    visible_tools = set(runtime.registry.ids())
    assert "write_file" not in visible_tools
    assert "edit_file" not in visible_tools
    assert "bash" not in visible_tools
    assert "read_file" in visible_tools
    assert "grep" in visible_tools


def test_hidden_title_and_compaction_agents_feed_session_state(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    assert runtime.run_turn("请只回复 ok。") == "ok"
    assert runtime.session.title == "Agent 系统测试"
    runtime.run_turn("第二轮")
    runtime.run_turn("第三轮")
    assert runtime.session.summary is not None
    assert runtime.session.summary.text == "Compact summary text"
    assert "I added an agent registry" in runtime.conversation_summary()


def test_runtime_can_create_and_reload_custom_agent(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    message = runtime.create_agent("TypeScript 代码审查专家")
    assert "ts-reviewer" in message
    agents = runtime.list_agents()
    assert "ts-reviewer" in agents
    detail = runtime.show_agent("ts-reviewer")
    assert "TypeScript code review specialist" in detail
