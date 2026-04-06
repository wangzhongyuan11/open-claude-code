import json
from pathlib import Path
import sys
import textwrap

from openagent.domain.messages import Message
from openagent.domain.session import SessionTodo
from openagent.domain.tools import ToolContext, ToolExecutionResult
from openagent.lsp import LspManager, LspServerInfo
from openagent.tools.builtin.aliases import EditTool, PatchTool, ReadTool, TaskTool, TodoReadTool, TodoWriteTool, WriteTool
from openagent.tools.builtin.bash import BashTool
from openagent.tools.builtin.integration import BatchTool, CodeSearchTool, LspTool, QuestionTool, ReadSymbolTool, SkillTool
from openagent.tools.builtin.web import WebFetchTool, WebSearchTool


class DummySubagentManager:
    def run(self, prompt: str, agent_name: str = "general", task_id: str | None = None):
        result = type("Result", (), {})()
        result.summary = "subagent completed"
        result.touched_paths = ["work/sub.txt"]
        result.verified_paths = ["work/sub.txt"]
        result.history = [Message(role="assistant", content="ok")]
        result.agent_name = agent_name
        result.task_id = task_id
        return result


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


def test_task_tool_passes_task_id_to_subagent_manager(tmp_path: Path):
    calls: dict[str, str | None] = {}

    class RecordingManager(DummySubagentManager):
        def run(self, prompt: str, agent_name: str = "general", task_id: str | None = None):
            calls["task_id"] = task_id
            return super().run(prompt, agent_name=agent_name, task_id=task_id)

    context = ToolContext(workspace=tmp_path)
    TaskTool(RecordingManager()).invoke(
        {
            "description": "Create delegated file",
            "prompt": "create it",
            "subagent_type": "general-purpose",
            "task_id": "task-1",
        },
        context,
    )

    assert calls["task_id"] == "task-1"


def test_delegate_and_task_normalize_agent_aliases(tmp_path: Path):
    from openagent.tools.builtin.delegate import DelegateTool

    context = ToolContext(workspace=tmp_path)
    delegate_result = DelegateTool(DummySubagentManager()).invoke(
        {"prompt": "do it", "agent": "coding"},
        context,
    )
    task_result = TaskTool(DummySubagentManager()).invoke(
        {
            "description": "Explore references",
            "prompt": "find references",
            "subagent_type": "research",
            "task_id": "task-2",
        },
        context,
    )
    assert delegate_result.metadata["agent"] == "general"
    assert task_result.metadata["subagent_type"] == "research"
    assert task_result.metadata["agent"] == "explore"


def test_delegate_normalizes_code_alias(tmp_path: Path):
    from openagent.tools.builtin.delegate import DelegateTool

    context = ToolContext(workspace=tmp_path)
    result = DelegateTool(DummySubagentManager()).invoke(
        {"prompt": "do it", "agent": "code"},
        context,
    )
    assert result.metadata["agent"] == "general"


def test_delegate_normalizes_generic_alias(tmp_path: Path):
    from openagent.tools.builtin.delegate import DelegateTool

    context = ToolContext(workspace=tmp_path)
    result = DelegateTool(DummySubagentManager()).invoke(
        {"prompt": "do it", "agent": "generic"},
        context,
    )
    assert result.metadata["agent"] == "general"


def test_delegate_normalizes_python_alias(tmp_path: Path):
    from openagent.tools.builtin.delegate import DelegateTool

    context = ToolContext(workspace=tmp_path)
    result = DelegateTool(DummySubagentManager()).invoke(
        {"prompt": "do it", "agent": "python"},
        context,
    )
    assert result.metadata["agent"] == "general"


def test_delegate_normalizes_simple_alias(tmp_path: Path):
    from openagent.tools.builtin.delegate import DelegateTool

    context = ToolContext(workspace=tmp_path)
    result = DelegateTool(DummySubagentManager()).invoke(
        {"prompt": "do it", "agent": "simple"},
        context,
    )
    assert result.metadata["agent"] == "general"


def test_task_normalizes_basic_alias(tmp_path: Path):
    context = ToolContext(workspace=tmp_path)
    result = TaskTool(DummySubagentManager()).invoke(
        {
            "description": "basic subtask",
            "prompt": "do it",
            "subagent_type": "basic",
            "task_id": "task-basic",
        },
        context,
    )
    assert result.metadata["agent"] == "general"


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
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Use for demo tasks.\n---\n# Demo Skill\nUse this skill.\n",
        encoding="utf-8",
    )
    (skill_dir / "notes.txt").write_text("note", encoding="utf-8")
    context = ToolContext(workspace=tmp_path, runtime_state={"skill_roots": [str(tmp_path / "skills")]})
    result = SkillTool().invoke({"name": "demo-skill"}, context)
    assert not result.is_error
    assert "<skill_content name=\"demo-skill\">" in result.content
    assert "notes.txt" in result.content


def test_skill_tool_lists_errors_for_invalid_skill(tmp_path: Path):
    invalid_dir = tmp_path / "skills" / "Bad Skill"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "SKILL.md").write_text("# Missing frontmatter\n", encoding="utf-8")
    context = ToolContext(workspace=tmp_path, runtime_state={"skill_roots": [str(tmp_path / "skills")]})

    result = SkillTool().invoke({"action": "list"}, context)

    assert not result.is_error
    assert "<skill_errors>" in result.content
    assert "frontmatter_error" in result.content


def test_skill_tool_filters_denied_skills_from_list(tmp_path: Path):
    root = tmp_path / "skills"
    for name in ["allowed-skill", "blocked-skill"]:
        skill_dir = root / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Use {name}.\n---\n# {name}\n",
            encoding="utf-8",
        )
    context = ToolContext(
        workspace=tmp_path,
        runtime_state={
            "skill_roots": [str(root)],
            "skill_allowed": lambda name: name != "blocked-skill",
        },
    )

    result = SkillTool().invoke({"action": "list"}, context)

    assert "allowed-skill" in result.content
    assert "blocked-skill" not in result.content
    assert result.metadata["denied_count"] == "1"


def test_skill_tool_denies_loading_blocked_skill(tmp_path: Path):
    root = tmp_path / "skills"
    skill_dir = root / "blocked-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: blocked-skill\ndescription: Use blocked skill.\n---\n# Blocked\n",
        encoding="utf-8",
    )
    context = ToolContext(
        workspace=tmp_path,
        runtime_state={"skill_roots": [str(root)], "skill_allowed": lambda _name: False},
    )

    result = SkillTool().invoke({"name": "blocked-skill"}, context)

    assert result.is_error
    assert result.error and result.error.type == "permission_denied"


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


def test_lsp_tool_uses_real_stdio_manager_when_available(tmp_path: Path):
    server_script = tmp_path / "fake_lsp.py"
    server_script.write_text(
        textwrap.dedent(
            """
            import json
            import sys

            docs = {}

            def send(payload):
                body = json.dumps(payload).encode("utf-8")
                sys.stdout.buffer.write(f"Content-Length: {len(body)}\\r\\n\\r\\n".encode("ascii") + body)
                sys.stdout.buffer.flush()

            def read_message():
                headers = {}
                while True:
                    line = sys.stdin.buffer.readline()
                    if not line:
                        return None
                    if line == b"\\r\\n":
                        break
                    text = line.decode("ascii").strip()
                    if ":" in text:
                        k, v = text.split(":", 1)
                        headers[k.lower()] = v.strip()
                length = int(headers.get("content-length", "0"))
                body = sys.stdin.buffer.read(length)
                return json.loads(body.decode("utf-8")) if body else None

            while True:
                msg = read_message()
                if msg is None:
                    break
                method = msg.get("method")
                if method == "initialize":
                    send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {}}})
                elif method == "initialized":
                    pass
                elif method == "shutdown":
                    send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
                elif method == "exit":
                    break
                elif method == "textDocument/didOpen":
                    item = msg["params"]["textDocument"]
                    docs[item["uri"]] = item["text"]
                elif method == "textDocument/definition":
                    uri = msg["params"]["textDocument"]["uri"]
                    send({"jsonrpc": "2.0", "id": msg["id"], "result": [{"uri": uri, "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 7}}}]})
                elif method == "textDocument/references":
                    uri = msg["params"]["textDocument"]["uri"]
                    send({"jsonrpc": "2.0", "id": msg["id"], "result": [{"uri": uri, "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 7}}}, {"uri": uri, "range": {"start": {"line": 2, "character": 4}, "end": {"line": 2, "character": 7}}}]})
                elif method == "textDocument/documentSymbol":
                    send({"jsonrpc": "2.0", "id": msg["id"], "result": [{"name": "add", "kind": 12, "range": {"start": {"line": 0, "character": 0}, "end": {"line": 1, "character": 16}}, "selectionRange": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 7}}}]})
                elif method == "textDocument/hover":
                    send({"jsonrpc": "2.0", "id": msg["id"], "result": {"contents": {"kind": "markdown", "value": "def add(a, b)"}}})
                elif method == "workspace/symbol":
                    uri = list(docs.keys())[0]
                    send({"jsonrpc": "2.0", "id": msg["id"], "result": [{"name": "add", "kind": 12, "location": {"uri": uri, "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 7}}}}]})
            """
        ),
        encoding="utf-8",
    )
    file_path = tmp_path / "mod.py"
    file_path.write_text("def add(a, b):\n    return a + b\n\nx = add(1, 2)\n", encoding="utf-8")
    manager = LspManager(
        tmp_path,
        servers=[
            LspServerInfo(
                id="fake-python",
                command=[sys.executable, str(server_script)],
                extensions=(".py",),
                language_ids={".py": "python"},
            )
        ],
    )
    context = ToolContext(workspace=tmp_path, runtime_state={"lsp_manager": manager})

    try:
        definition = LspTool().invoke(
            {"operation": "goToDefinition", "file_path": "mod.py", "line": 4, "character": 5},
            context,
        )
        references = LspTool().invoke(
            {"operation": "findReferences", "file_path": "mod.py", "line": 4, "character": 5},
            context,
        )
        hover = LspTool().invoke(
            {"operation": "hover", "file_path": "mod.py", "line": 4, "character": 5},
            context,
        )
        symbols = LspTool().invoke({"operation": "workspaceSymbol", "query": "add"}, context)
    finally:
        manager.close()

    assert not definition.is_error
    assert '"path": "mod.py"' in definition.content
    assert not references.is_error
    assert references.content.count('"path": "mod.py"') == 2
    assert not hover.is_error
    assert "def add(a, b)" in hover.content
    assert not symbols.is_error
    assert '"name": "add"' in symbols.content


def test_read_symbol_tool(tmp_path: Path):
    file_path = tmp_path / "mod.py"
    file_path.write_text("class Box:\n    pass\n\ndef add(a, b):\n    return a + b\n", encoding="utf-8")
    context = ToolContext(workspace=tmp_path)

    result = ReadSymbolTool().invoke({"path": "mod.py", "symbol": "add"}, context)

    assert not result.is_error
    assert "def add(a, b):" in result.content
    assert "return a + b" in result.content


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


def test_bash_tool_prepares_pytest_commands(tmp_path: Path):
    command = "cd work/demo && PYTHONPATH=src pytest tests/test_math_ops.py -q"

    prepared = BashTool._prepare_command(command, tmp_path)

    assert "PYTHONDONTWRITEBYTECODE=1" in prepared
    assert "__pycache__" in prepared
    assert prepared.endswith(command)
