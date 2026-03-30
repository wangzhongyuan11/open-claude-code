from pathlib import Path

from openagent.agent.runtime import AgentRuntime
from openagent.config.settings import Settings
from openagent.domain.messages import AgentResponse, ToolCall
from openagent.providers.base import BaseProvider
from openagent.session.manager import SessionManager
from openagent.session.store import SessionStore


class ScenarioProvider(BaseProvider):
    def __init__(self, scenario: str):
        self.scenario = scenario
        self.calls = 0

    def generate(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.scenario == "create_file":
            if self.calls == 1:
                return AgentResponse(
                    text="先创建文件。",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="write_file",
                            arguments={"path": "notes.txt", "content": "hello"},
                        )
                    ],
                )
            return AgentResponse(text="文件已创建。")

        if self.scenario == "edit_file":
            if self.calls == 1:
                return AgentResponse(
                    text="先改一下内容。",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="edit_file",
                            arguments={"path": "notes.txt", "old_text": "hello", "new_text": "hello agent"},
                        )
                    ],
                )
            return AgentResponse(text="文件已修改。")

        if self.scenario == "delegate":
            if self.calls == 1:
                return AgentResponse(
                    text="交给子代理处理。",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="delegate",
                            arguments={"prompt": "创建 child.txt，内容为 subagent"},
                        )
                    ],
                )
            return AgentResponse(text="子代理任务已完成。")

        raise AssertionError(f"unknown scenario: {self.scenario}")


class ChildScenarioProvider(BaseProvider):
    def __init__(self):
        self.calls = 0

    def generate(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[
                    ToolCall(
                        id="child-1",
                        name="write_file",
                        arguments={"path": "child.txt", "content": "subagent"},
                    )
                ]
            )
        return AgentResponse(text="子代理已创建 child.txt。")


def build_runtime(tmp_path: Path, provider: BaseProvider, provider_factory=None) -> AgentRuntime:
    settings = Settings.from_workspace(tmp_path)
    manager = SessionManager(SessionStore(settings.session_root))
    session = manager.start(workspace=tmp_path)
    return AgentRuntime(
        provider=provider,
        provider_factory=provider_factory or (lambda: provider),
        workspace=tmp_path,
        session_manager=manager,
        session=session,
        settings=settings,
    )


def test_runtime_task_create_file(tmp_path: Path):
    runtime = build_runtime(tmp_path, ScenarioProvider("create_file"))

    reply = runtime.run_turn("创建 notes.txt")

    assert reply == "文件已创建。"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello"


def test_runtime_task_edit_file(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    runtime = build_runtime(tmp_path, ScenarioProvider("edit_file"))

    reply = runtime.run_turn("修改 notes.txt")

    assert reply == "文件已修改。"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello agent"


def test_runtime_task_delegate_to_subagent(tmp_path: Path):
    runtime = build_runtime(
        tmp_path,
        ScenarioProvider("delegate"),
        provider_factory=ChildScenarioProvider,
    )

    reply = runtime.run_turn("让子代理创建 child.txt")

    assert reply == "子代理任务已完成。"
    assert (tmp_path / "child.txt").read_text(encoding="utf-8") == "subagent"


def test_runtime_continues_incomplete_multistep_request(tmp_path: Path):
    class MultiStepProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="write_file",
                            arguments={"path": "demo/README.md", "content": "hello"},
                        )
                    ],
                    finish="tool-calls",
                )
            if self.calls == 2:
                return AgentResponse(text="先停一下。", finish="stop")
            if self.calls == 3:
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-2",
                            name="write_file",
                            arguments={"path": "demo/app.json", "content": '{"mode": "production"}'},
                        )
                    ],
                    finish="tool-calls",
                )
            return AgentResponse(text="任务全部完成", finish="stop")

    runtime = build_runtime(tmp_path, MultiStepProvider())

    reply = runtime.run_turn(
        "1. 创建文件 `demo/README.md`，内容为：\n\nhello\n\n"
        "2. 创建文件 `demo/app.json`，内容为：\n\n{\"mode\": \"production\"}\n\n"
        "10. 最后直接告诉我：如果都成功，就回复“任务全部完成”"
    )

    assert (tmp_path / "demo" / "README.md").read_text(encoding="utf-8") == "hello"
    assert (tmp_path / "demo" / "app.json").read_text(encoding="utf-8") == '{"mode": "production"}'
    assert "任务全部完成" in reply or "已完成" in reply


def test_runtime_completes_full_checklist_request_with_continuation_and_delegate(tmp_path: Path):
    class ChecklistProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="bash",
                            arguments={"command": f"mkdir -p {tmp_path / 'work/demo_project/docs'} {tmp_path / 'work/demo_project/config'} {tmp_path / 'work/demo_project/logs'}"},
                        )
                    ],
                    finish="tool-calls",
                )
            if self.calls == 2:
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-2",
                            name="write_file",
                            arguments={
                                "path": "work/demo_project/docs/README.md",
                                "content": "# Demo Project\n\n这是一个用于测试 session、tool call、delegate、revert、retry 的示例项目。\n\n## Tasks\n- create files\n- read files\n- edit files\n- delegate subtask",
                            },
                        )
                    ],
                    finish="tool-calls",
                )
            if self.calls == 3:
                return AgentResponse(text="已完成前几步。", finish="stop")
            if self.calls == 4:
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-3",
                            name="write_file",
                            arguments={
                                "path": "work/demo_project/config/app.json",
                                "content": '{\n  "name": "demo_project",\n  "version": "1.0",\n  "mode": "production",\n  "features": ["session", "tools", "delegate"]\n}',
                            },
                        )
                    ],
                    finish="tool-calls",
                )
            if self.calls == 5:
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-4",
                            name="write_file",
                            arguments={
                                "path": "work/demo_project/logs/run.log",
                                "content": "[INIT] demo project created\n[STATUS] verified\n",
                            },
                        )
                    ],
                    finish="tool-calls",
                )
            if self.calls == 6:
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-5",
                            name="delegate",
                            arguments={"prompt": "创建文件 work/demo_project/docs/subtask_note.txt，内容为 this file is created by delegated agent"},
                        )
                    ],
                    finish="tool-calls",
                )
            return AgentResponse(text="任务全部完成", finish="stop")

    class ChecklistChildProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="child-1",
                            name="write_file",
                            arguments={
                                "path": "work/demo_project/docs/subtask_note.txt",
                                "content": "this file is created by delegated agent",
                            },
                        )
                    ],
                    finish="tool-calls",
                )
            return AgentResponse(text="子代理任务已完成。", finish="stop")

    runtime = build_runtime(
        tmp_path,
        ChecklistProvider(),
        provider_factory=ChecklistChildProvider,
    )

    reply = runtime.run_turn(
        "1. 创建目录 `work/demo_project`，以及子目录：\n"
        "   - `work/demo_project/docs`\n"
        "   - `work/demo_project/config`\n"
        "   - `work/demo_project/logs`\n\n"
        "2. 创建文件 `work/demo_project/docs/README.md`，内容为：\n\n"
        "# Demo Project\n\n"
        "这是一个用于测试 session、tool call、delegate、revert、retry 的示例项目。\n\n"
        "## Tasks\n- create files\n- read files\n- edit files\n- delegate subtask\n\n"
        "3. 创建文件 `work/demo_project/config/app.json`，内容为：\n\n"
        "{\n  \"name\": \"demo_project\",\n  \"version\": \"1.0\",\n  \"mode\": \"test\",\n  \"features\": [\"session\", \"tools\", \"delegate\"]\n}\n\n"
        "4. 创建文件 `work/demo_project/logs/run.log`，内容为：\n\n"
        "[INIT] demo project created\n[STATUS] pending verification\n\n"
        "6. 将 `work/demo_project/config/app.json` 中的 `\"mode\": \"test\"` 修改为 `\"mode\": \"production\"`。\n\n"
        "7. 将 `work/demo_project/logs/run.log` 中的第二行\n`[STATUS] pending verification`\n修改为\n`[STATUS] verified`\n\n"
        "8. 请把下面任务委托给子代理完成：创建文件 `work/demo_project/docs/subtask_note.txt`，内容为：`this file is created by delegated agent`\n\n"
        "10. 最后直接告诉我：如果都成功，就回复“任务全部完成”"
    )

    assert (tmp_path / "work/demo_project/docs/README.md").read_text(encoding="utf-8").rstrip().endswith("delegate subtask")
    assert '"mode": "production"' in (tmp_path / "work/demo_project/config/app.json").read_text(encoding="utf-8")
    assert (tmp_path / "work/demo_project/logs/run.log").read_text(encoding="utf-8") == "[INIT] demo project created\n[STATUS] verified\n"
    assert (tmp_path / "work/demo_project/docs/subtask_note.txt").read_text(encoding="utf-8") == "this file is created by delegated agent"
    assert "任务全部完成" in reply


def test_runtime_stops_after_final_multistep_verification_reads(tmp_path: Path):
    class MultiReadProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return AgentResponse(
                    tool_calls=[ToolCall(id="c1", name="ensure_dir", arguments={"path": "work/multi/docs"})],
                    finish="tool-calls",
                )
            if self.calls == 2:
                return AgentResponse(
                    tool_calls=[ToolCall(id="c2", name="write_file", arguments={"path": "work/multi/docs/README.md", "content": "# Demo\ndelegate subtask"})],
                    finish="tool-calls",
                )
            if self.calls == 3:
                return AgentResponse(
                    tool_calls=[ToolCall(id="c3", name="ensure_dir", arguments={"path": "work/multi/config"})],
                    finish="tool-calls",
                )
            if self.calls == 4:
                return AgentResponse(
                    tool_calls=[ToolCall(id="c4", name="write_file", arguments={"path": "work/multi/config/app.json", "content": '{"mode": "production"}'})],
                    finish="tool-calls",
                )
            if self.calls == 5:
                return AgentResponse(
                    tool_calls=[ToolCall(id="c5", name="write_file", arguments={"path": "work/multi/docs/subtask.txt", "content": "delegated-ok"})],
                    finish="tool-calls",
                )
            if self.calls == 6:
                return AgentResponse(
                    tool_calls=[ToolCall(id="c6", name="read_file", arguments={"path": "work/multi/docs/README.md"})],
                    finish="tool-calls",
                )
            if self.calls == 7:
                return AgentResponse(
                    tool_calls=[ToolCall(id="c7", name="read_file", arguments={"path": "work/multi/config/app.json"})],
                    finish="tool-calls",
                )
            return AgentResponse(
                tool_calls=[ToolCall(id="c8", name="read_file", arguments={"path": "work/multi/docs/subtask.txt"})],
                finish="tool-calls",
            )

    runtime = build_runtime(tmp_path, MultiReadProvider())
    reply = runtime.run_turn(
        "请严格按顺序完成：\n"
        "1. 创建 work/multi 及 docs、config 子目录。\n"
        "2. 写入 docs/README.md，内容包含标题 Demo 和一行 delegate subtask。\n"
        "3. 写入 config/app.json，mode 是 test。\n"
        "4. 把 mode 改成 production。\n"
        "5. 委派子代理创建 work/multi/docs/subtask.txt，内容 delegated-ok。\n"
        "6. 最后读取 README.md、app.json、subtask.txt，只告诉我三件事：README 是否含 delegate subtask；mode 是否为 production；子代理是否成功。"
    )
    assert "README 是否含 delegate subtask：是" in reply
    assert "mode 是否为 production：是" in reply
    assert "子代理是否成功：是" in reply
    assert any(todo.source == "auto-checklist" for todo in runtime.session.todos)
    assert all(todo.status == "completed" for todo in runtime.session.todos if todo.source == "auto-checklist")


def test_checklist_creation_step_remains_completed_after_later_edit(tmp_path: Path):
    from openagent.domain.messages import Message
    from openagent.session.task_validation import parse_multistep_requirements

    runtime = build_runtime(tmp_path, ScenarioProvider("create_file"))
    prompt = (
        "1. 创建文件 `work/demo/config/app.json`，内容为：\n\n"
        "{\n  \"mode\": \"test\"\n}\n\n"
        "2. 将 `work/demo/config/app.json` 中的 `\"mode\": \"test\"` 修改为 `\"mode\": \"production\"`。"
    )
    requirements = parse_multistep_requirements(prompt)
    runtime.session_manager.append_message(runtime.session, Message(role="user", content=prompt), mark_running_state=True)
    runtime.session_manager.sync_checklist(runtime.session, requirements)
    config_dir = tmp_path / "work" / "demo" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "app.json").write_text('{\n  "mode": "production"\n}\n', encoding="utf-8")
    runtime.session_manager.sync_checklist_progress(runtime.session, requirements)

    auto_checklist = [todo for todo in runtime.session.todos if todo.source == "auto-checklist"]
    assert auto_checklist
    assert all(todo.status == "completed" for todo in auto_checklist)


def test_runtime_preserves_auto_checklist_when_model_writes_matching_todos(tmp_path: Path):
    from openagent.domain.session import SessionTodo

    runtime = build_runtime(tmp_path, ScenarioProvider("create_file"))
    runtime.session.todos = [
        SessionTodo(content="[1] 创建目录 demo", source="auto-checklist", key="checklist:1"),
        SessionTodo(content="[2] 创建文件 demo/app.json", source="auto-checklist", key="checklist:2"),
    ]
    runtime._set_todos(
        [
            SessionTodo(content="创建目录 demo", status="done", priority="high"),
            SessionTodo(content="创建文件 demo/app.json", status="completed", priority="medium"),
        ]
    )

    assert all(todo.source == "auto-checklist" for todo in runtime.session.todos)
    assert all(todo.status == "completed" for todo in runtime.session.todos)
