from pathlib import Path

from openagent.agent.loop import AgentLoop
from openagent.domain.messages import AgentResponse, Message, ToolCall
from openagent.domain.tools import ToolContext
from openagent.providers.base import BaseProvider
from openagent.tools.builtin.files import ReadFileTool, WriteFileTool
from openagent.tools.registry import ToolRegistry


class RepetitiveProvider(BaseProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="write_file",
                        arguments={"path": "loop.txt", "content": "ok"},
                    )
                ]
            )
        return AgentResponse(
            tool_calls=[
                ToolCall(
                    id=f"call-{self.calls}",
                    name="read_file",
                    arguments={"path": "loop.txt"},
                )
            ]
        )


def test_agent_loop_returns_fallback_on_repetitive_tool_loop(tmp_path: Path):
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(ReadFileTool())
    loop = AgentLoop(
        provider=RepetitiveProvider(),
        tool_registry=registry,
        tool_context=ToolContext(workspace=tmp_path),
    )

    history = loop.run([Message(role="user", content="loop")], max_steps=12)

    assert history[-1].role == "assistant"
    assert "repetitive_tool_loop" in history[-1].content
    assert "Last tool result:\nok" in history[-1].content
