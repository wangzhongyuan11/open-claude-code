import json
from pathlib import Path

from openagent.agent.loop import AgentLoop
from openagent.domain.messages import AgentResponse, Message, ToolCall
from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.providers.base import BaseProvider
from openagent.tools.builtin.files import WriteFileTool
from openagent.tools.registry import ToolRegistry


class EventProvider(BaseProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name="write_file",
                        arguments={"path": "a.txt", "content": "x"},
                    )
                ]
            )
        return AgentResponse(text="done")


def test_agent_loop_emits_events(tmp_path: Path):
    log_file = tmp_path / "events.jsonl"
    bus = EventBus(log_file)
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    loop = AgentLoop(
        provider=EventProvider(),
        tool_registry=registry,
        tool_context=ToolContext(workspace=tmp_path),
        event_bus=bus,
    )

    loop.run([Message(role="user", content="create file")])

    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    event_types = [line["type"] for line in lines]

    assert "model.requested" in event_types
    assert "tool.called" in event_types
    assert "tool.pending" in event_types
    assert "tool.running" in event_types
    assert "tool.succeeded" in event_types
    assert "tool.completed" in event_types
