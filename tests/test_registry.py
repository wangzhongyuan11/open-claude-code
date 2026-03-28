import json

from openagent.events.bus import EventBus
from openagent.tools.builtin.files import ReadFileTool
from openagent.tools.base import BaseTool
from openagent.tools.registry import ToolRegistry
from openagent.domain.tools import ToolContext, ToolExecutionResult, ToolOutputLimits


def test_registry_register_and_specs():
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    specs = registry.specs()

    assert len(specs) == 1
    assert specs[0].id == "read_file"
    assert specs[0].name == "read_file"


class CrashTool(BaseTool):
    name = "crash"
    description = "crashes"
    input_schema = {"type": "object", "properties": {}}

    def invoke(self, arguments, context):
        raise RuntimeError("boom")


def test_registry_invoke_catches_tool_exceptions(tmp_path):
    registry = ToolRegistry()
    registry.register(CrashTool())

    result = registry.invoke("crash", {}, ToolContext(workspace=tmp_path))

    assert result.is_error is True
    assert "tool 'crash' failed" in result.content
    assert "RuntimeError: boom" in result.content
    assert result.error is not None
    assert result.error.type == "RuntimeError"


class VerboseTool(BaseTool):
    name = "verbose"
    description = "returns lots of output"
    input_schema = {"type": "object", "properties": {}}
    output_limits = ToolOutputLimits(max_chars=20, max_lines=2, direction="head")

    def invoke(self, arguments, context):
        return ToolExecutionResult.success("line-1\nline-2\nline-3\nline-4", title="Verbose output")


def test_registry_truncates_large_results_and_emits_lifecycle_events(tmp_path):
    bus = EventBus(tmp_path / "events.jsonl")
    registry = ToolRegistry()
    registry.register(VerboseTool())

    result = registry.invoke(
        "verbose",
        {},
        ToolContext(workspace=tmp_path, session_id="sess-1", tool_call_id="call-1", event_bus=bus),
    )

    assert result.truncated is True
    assert "Full output saved to:" in result.content
    assert result.metadata["output_path"]
    assert result.artifacts[0].kind == "tool-output"

    lines = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    event_types = [line["type"] for line in lines]
    assert event_types[:2] == ["tool.pending", "tool.running"]
    assert "tool.succeeded" in event_types


def test_registry_returns_structured_failure_for_unknown_tool(tmp_path):
    registry = ToolRegistry()

    result = registry.invoke("missing_tool", {}, ToolContext(workspace=tmp_path))

    assert result.is_error is True
    assert result.error is not None
    assert result.error.type == "unknown_tool"
    assert "unknown tool" in result.content
