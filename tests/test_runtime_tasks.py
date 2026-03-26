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
