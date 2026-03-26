from openagent.tools.builtin.files import ReadFileTool
from openagent.tools.base import BaseTool
from openagent.tools.registry import ToolRegistry
from openagent.domain.tools import ToolContext


def test_registry_register_and_specs():
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    specs = registry.specs()

    assert len(specs) == 1
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
