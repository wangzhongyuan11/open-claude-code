from pathlib import Path

from openagent.agent.loop import AgentLoop
from openagent.agent.subagent import SubagentManager
from openagent.domain.messages import AgentResponse, Message, ToolCall
from openagent.domain.tools import ToolContext
from openagent.providers.base import BaseProvider
from openagent.tools.builtin.delegate import DelegateTool
from openagent.tools.builtin.files import ReadFileTool, WriteFileTool
from openagent.tools.registry import ToolRegistry


class ChildProvider(BaseProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[
                    ToolCall(
                        id="child-tool-1",
                        name="write_file",
                        arguments={"path": "child.txt", "content": "from subagent"},
                    )
                ]
            )
        return AgentResponse(text="subagent finished")


class ParentProvider(BaseProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[
                    ToolCall(
                        id="parent-tool-1",
                        name="delegate",
                        arguments={"prompt": "create child.txt"},
                    )
                ]
            )
        return AgentResponse(text="parent finished")


def build_subagent_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(ReadFileTool())
    return registry


def test_subagent_manager_runs_isolated_loop(tmp_path: Path):
    manager = SubagentManager(
        provider_factory=ChildProvider,
        registry_factory=build_subagent_registry,
        workspace=tmp_path,
        system_prompt="subagent prompt",
    )

    result = manager.run("create child.txt")

    assert result.summary == "subagent finished"
    assert (tmp_path / "child.txt").read_text(encoding="utf-8") == "from subagent"


def test_delegate_tool_integrates_with_parent_agent_loop(tmp_path: Path):
    manager = SubagentManager(
        provider_factory=ChildProvider,
        registry_factory=build_subagent_registry,
        workspace=tmp_path,
        system_prompt="subagent prompt",
    )
    registry = ToolRegistry()
    registry.register(DelegateTool(manager))

    loop = AgentLoop(
        provider=ParentProvider(),
        tool_registry=registry,
        tool_context=ToolContext(workspace=tmp_path),
    )

    history = loop.run([Message(role="user", content="delegate this")])

    assert history[-1].content == "parent finished"
    assert any(message.role == "tool" and message.content == "subagent finished" for message in history)
