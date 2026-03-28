from pathlib import Path

from openagent.domain.tools import ToolContext
from openagent.tools.builtin.bash import BashTool
from openagent.tools.builtin.edit import EditFileTool, MultiEditTool
from openagent.tools.builtin.files import AppendFileTool, ListFilesTool, ReadFileRangeTool, ReadFileTool, WriteFileTool
from openagent.tools.builtin.patch import ApplyPatchTool
from openagent.tools.builtin.search import GlobTool, GrepTool, LsTool


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


def test_read_file_range_tool(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = ReadFileRangeTool().invoke({"path": "a.txt", "start_line": 2, "end_line": 3}, context)

    assert result.content == "two\nthree"


def test_read_file_range_tool_clamps_zero_to_first_line(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    (tmp_path / "a.txt").write_text("one\ntwo\n", encoding="utf-8")

    result = ReadFileRangeTool().invoke({"path": "a.txt", "start_line": 0, "end_line": 1}, context)

    assert result.content == "one"


def test_ls_glob_and_grep_tools(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("VALUE = 3\n", encoding="utf-8")

    ls_result = LsTool().invoke({"path": "pkg"}, context)
    glob_result = GlobTool().invoke({"pattern": "*.py", "base_path": "pkg"}, context)
    grep_result = GrepTool().invoke({"pattern": "VALUE", "path_glob": "pkg/*.py"}, context)

    assert "pkg/a.py" in ls_result.content
    assert "pkg/a.py" in glob_result.content
    assert "pkg/a.py:1: VALUE = 1" in grep_result.content
    assert "notes.txt" not in grep_result.content


def test_grep_tool_supports_recursive_double_star_glob(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    (tmp_path / "work" / "cli_chain").mkdir(parents=True)
    (tmp_path / "work" / "cli_chain" / "math_utils.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    result = GrepTool().invoke({"pattern": "def add", "path_glob": "work/cli_chain/**/*.py"}, context)

    assert "work/cli_chain/math_utils.py:1: def add(a, b):" in result.content


def test_grep_tool_accepts_workspace_absolute_path_glob(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("TOKEN = 1\n", encoding="utf-8")

    result = GrepTool().invoke({"pattern": "TOKEN", "path_glob": str(tmp_path / "pkg" / "*.py")}, context)

    assert "pkg/mod.py:1: TOKEN = 1" in result.content


def test_apply_patch_tool(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    (tmp_path / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    patch = """--- a/a.txt
+++ b/a.txt
@@ -1,2 +1,2 @@
 one
-two
+three
"""

    result = ApplyPatchTool().invoke({"patch": patch}, context)

    assert not result.is_error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one\nthree\n"


def test_multiedit_tool(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    (tmp_path / "a.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = MultiEditTool().invoke(
        {
            "path": "a.txt",
            "edits": [
                {"old_text": "alpha", "new_text": "alpha-1"},
                {"old_text": "gamma", "new_text": "gamma-1"},
            ],
        },
        context,
    )

    assert not result.is_error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "alpha-1\nbeta\ngamma-1\n"
