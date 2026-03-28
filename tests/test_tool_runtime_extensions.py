import json
from pathlib import Path

from openagent.domain.messages import Message
from openagent.domain.session import SessionTodo
from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.tools.builtin.aliases import EditTool, PatchTool, ReadTool, TaskTool, TodoReadTool, TodoWriteTool, WriteTool
from openagent.tools.builtin.integration import BatchTool, CodeSearchTool, LspTool, QuestionTool, SkillTool
from openagent.tools.builtin.web import WebFetchTool, WebSearchTool


class DummySubagentManager:
    def run(self, prompt: str):
        class Result:
            summary = "subagent completed"
            touched_paths = ["work/sub.txt"]
            verified_paths = ["work/sub.txt"]
            history = [Message(role="assistant", content="ok")]

        return Result()


def test_alias_read_write_edit_and_patch_tools(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    WriteTool().invoke({"path": "a.txt", "content": "alpha\nbeta\n"}, context)
    read_range = ReadTool().invoke({"path": "a.txt", "start_line": 1, "end_line": 1}, context)
    edit_result = EditTool().invoke({"path": "a.txt", "old_text": "beta", "new_text": "gamma"}, context)
    patch = """--- a/a.txt
+++ b/a.txt
@@ -1,2 +1,2 @@
 alpha
-gamma
+delta
"""
    patch_result = PatchTool().invoke({"patch": patch.replace("++++", "+++")}, context)
    assert read_range.content == "alpha"
    assert not edit_result.is_error
    assert not patch_result.is_error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "alpha\ndelta\n"


def test_todo_read_write_tools(tmp_path: Path):
    todos: list[SessionTodo] = [SessionTodo(content="old")]

    def set_todos(new_todos):
        todos.clear()
        todos.extend(new_todos)

    context = ToolContext(
        workspace=tmp_path,
        runtime_state={
            "set_todos": set_todos,
            "get_todos": lambda: list(todos),
        },
    )
    write_result = TodoWriteTool().invoke(
        {"todos": [{"content": "verify", "status": "pending", "priority": "high"}]},
        context,
    )
    read_result = TodoReadTool().invoke({}, context)
    assert not write_result.is_error
    assert '"content": "verify"' in write_result.content
    assert '"content": "verify"' in read_result.content


def test_task_tool_returns_structured_task_result(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    result = TaskTool(DummySubagentManager()).invoke(
        {
            "description": "Create delegated file",
            "prompt": "create it",
            "subagent_type": "general-purpose",
            "task_id": "task-1",
        },
        context,
    )
    assert not result.is_error
    assert "task_id: task-1" in result.content
    assert "<task_result>" in result.content


def test_question_tool_uses_runtime_handler(tmp_path: Path):
    context = ToolContext(
        workspace=tmp_path,
        runtime_state={"ask_questions": lambda questions: ["answer-1", "answer-2"]},
    )
    result = QuestionTool().invoke(
        {
            "questions": [
                {"question": "What should I name the file?"},
                {"question": "Should I run tests?"},
            ]
        },
        context,
    )
    assert not result.is_error
    assert "answer-1" in result.content
    assert "answer-2" in result.content


def test_skill_tool_loads_skill_content(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Demo Skill\nUse this skill.\n", encoding="utf-8")
    (skill_dir / "notes.txt").write_text("note", encoding="utf-8")
    context = ToolContext(workspace=tmp_path, runtime_state={"skill_roots": [str(tmp_path / "skills")]})
    result = SkillTool().invoke({"name": "demo-skill"}, context)
    assert not result.is_error
    assert "<skill_content name=\"demo-skill\">" in result.content
    assert "notes.txt" in result.content


def test_lsp_python_fallback_and_codesearch(tmp_path: Path):
    file_path = tmp_path / "mod.py"
    file_path.write_text("def add(a, b):\n    return a + b\n\nx = add(1, 2)\n", encoding="utf-8")
    context = ToolContext(workspace=tmp_path)
    lsp_result = LspTool().invoke(
        {"operation": "goToDefinition", "file_path": "mod.py", "line": 4, "character": 5},
        context,
    )
    code_result = CodeSearchTool().invoke({"pattern": "return a \\+ b"}, context)
    assert not lsp_result.is_error
    assert "add" in lsp_result.content
    assert "mod.py:2:     return a + b" in code_result.content


def test_batch_tool_uses_runtime_invoke_callback(tmp_path: Path):
    def invoke_tool(name, arguments, parent_context=None):
        return ToolExecutionResult.success(f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}", title=name)

    context = ToolContext(workspace=tmp_path, runtime_state={"invoke_tool": invoke_tool})
    result = BatchTool().invoke(
        {
            "calls": [
                {"tool": "echo", "arguments": {"x": 1}},
                {"tool": "sum", "arguments": {"a": 2, "b": 3}},
            ]
        },
        context,
    )
    assert not result.is_error
    payload = json.loads(result.content)
    assert payload[0]["tool"] == "echo"
    assert payload[1]["status"] == "succeeded"


def test_webfetch_and_websearch(monkeypatch, tmp_path: Path):
    def fake_fetch(url: str, timeout: int = 20):
        if "duckduckgo" in url:
            return (
                '<a class="result__a" href="https://example.com/a">Example A</a>'
                '<a class="result__snippet">First result</a>',
                "text/html",
            )
        return ("<html><body><h1>Demo</h1><p>Hello web.</p></body></html>", "text/html")

    monkeypatch.setattr("openagent.tools.builtin.web._fetch_url", fake_fetch)
    context = ToolContext(workspace=tmp_path)
    fetch_result = WebFetchTool().invoke({"url": "https://example.com"}, context)
    search_result = WebSearchTool().invoke({"query": "demo search"}, context)
    assert not fetch_result.is_error
    assert "Hello web." in fetch_result.content
    assert not search_result.is_error
    assert "Example A" in search_result.content
