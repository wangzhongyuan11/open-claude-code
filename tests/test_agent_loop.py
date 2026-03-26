from pathlib import Path

from openagent.agent.loop import AgentLoop
from openagent.domain.messages import AgentResponse, Message, ToolCall
from openagent.domain.tools import ToolContext
from openagent.providers.base import BaseProvider
from openagent.tools.builtin.files import ReadFileTool, WriteFileTool
from openagent.tools.registry import ToolRegistry


class FakeProvider(BaseProvider):
    def __init__(self):
        self.calls = 0

    def generate(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="write_file",
                        arguments={"path": "hello.txt", "content": "hello"},
                    )
                ]
            )
        return AgentResponse(text="done")


def test_agent_loop_executes_tool_calls(tmp_path: Path):
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(ReadFileTool())
    provider = FakeProvider()
    loop = AgentLoop(
        provider=provider,
        tool_registry=registry,
        tool_context=ToolContext(workspace=tmp_path),
    )

    history = loop.run([Message(role="user", content="create a file")])

    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello"
    assert history[-1].role == "assistant"
    assert history[-1].content == "done"
