from pathlib import Path

from openagent.domain.tools import ToolContext
from openagent.tools.builtin.bash import BashTool
from openagent.tools.builtin.edit import EditFileTool
from openagent.tools.builtin.files import AppendFileTool, ListFilesTool, ReadFileTool, WriteFileTool


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


def test_list_files_ignores_runtime_state_dirs(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / ".openagent").mkdir()
    (tmp_path / ".openagent" / "state.json").write_text("x", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("ok", encoding="utf-8")
    context = ToolContext(workspace=tmp_path)

    result = ListFilesTool().invoke({}, context)

    assert result.content == "visible.txt"


def test_append_file_tool(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    writer = WriteFileTool()
    appender = AppendFileTool()

    writer.invoke({"path": "a.txt", "content": "alpha\n"}, context)
    result = appender.invoke({"path": "a.txt", "content": "beta\n"}, context)

    assert not result.is_error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "alpha\nbeta\n"
