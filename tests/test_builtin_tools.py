from pathlib import Path

from openagent.domain.tools import ToolContext
from openagent.tools.builtin.bash import BashTool
from openagent.tools.builtin.edit import EditFileTool
from openagent.tools.builtin.files import ReadFileTool, WriteFileTool


def test_write_read_and_edit_file(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    writer = WriteFileTool()
    reader = ReadFileTool()
    editor = EditFileTool()

    writer.invoke({"path": "a.txt", "content": "hello world"}, context)
    edit_result = editor.invoke(
        {"path": "a.txt", "old_text": "world", "new_text": "agent"},
        context,
    )
    read_result = reader.invoke({"path": "a.txt"}, context)

    assert not edit_result.is_error
    assert read_result.content == "hello agent"


def test_bash_tool(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    tool = BashTool()

    result = tool.invoke({"command": "printf 'ok'"}, context)

    assert not result.is_error
    assert result.content == "ok"
