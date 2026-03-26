from openagent.tools.builtin.files import ReadFileTool
from openagent.tools.registry import ToolRegistry


def test_registry_register_and_specs():
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    specs = registry.specs()

    assert len(specs) == 1
    assert specs[0].name == "read_file"
