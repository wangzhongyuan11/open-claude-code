from pathlib import Path

from openagent.agent.loop import AgentLoop
from openagent.agent.runtime import AgentRuntime
from openagent.config.settings import Settings
from openagent.domain.messages import AgentResponse, Message
from openagent.domain.session import SessionStatus
from openagent.providers.base import BaseProvider
from openagent.session.manager import SessionManager
from openagent.session.store import SessionStore
from openagent.session.todo import render_todos


class EchoProvider(BaseProvider):
    def generate(self, messages, tools, system_prompt=None):
        last_user = next(message.content for message in reversed(messages) if message.role == "user")
        return AgentResponse(text=f"echo:{last_user}")


def build_runtime(tmp_path: Path, compact_max_messages: int = 4) -> AgentRuntime:
    settings = Settings.from_workspace(tmp_path)
    settings.compact_max_messages = compact_max_messages
    settings.prompt_recent_messages = 4
    settings.prompt_max_tokens = 200
    manager = SessionManager(
        SessionStore(settings.session_root),
        max_messages_before_compact=settings.compact_max_messages,
        prompt_recent_messages=settings.prompt_recent_messages,
        prompt_max_tokens=settings.prompt_max_tokens,
    )
    session = manager.start(workspace=tmp_path)
    return AgentRuntime(
        provider=EchoProvider(),
        provider_factory=EchoProvider,
        workspace=tmp_path,
        session_manager=manager,
        session=session,
        settings=settings,
    )


def test_session_store_roundtrip_preserves_status_summary_and_todos(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    manager = SessionManager(store)
    session = manager.start(workspace=tmp_path)
    session.summary = None
    session.status = SessionStatus(state="degraded", last_error="x", recovery_hint="retry")
    manager.add_todo(session, "repair session")

    loaded = store.load(session.id)

    assert loaded.status.state == "degraded"
    assert loaded.status.recovery_hint == "retry"
    assert loaded.todos[0].content == "repair session"


def test_compaction_creates_summary_and_keeps_recent_messages(tmp_path: Path):
    runtime = build_runtime(tmp_path, compact_max_messages=4)

    for index in range(4):
        runtime.run_turn(f"msg-{index}")

    assert runtime.session.summary is not None
    assert runtime.session.summary.compacted_message_count > 0
    status = runtime.status_report()
    assert '"summary_present": true' in status
    assert '"prompt_token_estimate":' in status
    assert '"compaction_mode":' in status


def test_revert_last_turn_removes_latest_user_turn(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    runtime.run_turn("first")
    runtime.run_turn("second")

    result = runtime.revert_last_turn()

    assert result == "Reverted last turn."
    assert runtime.session.messages[-1].content == "echo:first"


def test_interrupted_session_recovers_as_degraded(tmp_path: Path):
    settings = Settings.from_workspace(tmp_path)
    store = SessionStore(settings.session_root)
    manager = SessionManager(store)
    session = manager.start(workspace=tmp_path)
    session.status = SessionStatus(state="running", last_user_message="unfinished")
    store.save(session)

    recovered = manager.start(workspace=tmp_path, session_id=session.id)

    assert recovered.status.state == "degraded"
    assert recovered.status.recovery_hint is not None


def test_todo_commands_are_persisted(tmp_path: Path):
    runtime = build_runtime(tmp_path)

    runtime.add_todo("verify session", "high")
    runtime.complete_todo(0)

    assert "[completed] (high) verify session" in render_todos(runtime.session)


def test_session_manager_assigns_message_relationships(tmp_path: Path):
    runtime = build_runtime(tmp_path)

    runtime.run_turn("link messages")

    user_message = next(message for message in runtime.session.messages if message.role == "user")
    assistant_message = next(message for message in runtime.session.messages if message.role == "assistant")

    assert user_message.session_id == runtime.session.id
    assert assistant_message.session_id == runtime.session.id
    assert assistant_message.parent_id == user_message.id
    assert assistant_message.finish == "stop"
    assert runtime.session.title == "link messages"


def test_prompt_context_includes_summary_and_runtime_note(tmp_path: Path):
    runtime = build_runtime(tmp_path, compact_max_messages=2)
    runtime.run_turn("first turn")
    runtime.run_turn("second turn")
    runtime.run_turn("third turn")

    prompt = runtime.session_manager.build_prompt(runtime.session, runtime.system_prompt)

    assert any(message.agent == "summary" for message in prompt.messages)
    assert any(message.agent == "context" for message in prompt.messages)
    assert prompt.estimated_tokens > 0


def test_processor_creates_step_and_tool_parts(tmp_path: Path):
    class ToolProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                from openagent.domain.messages import ToolCall

                return AgentResponse(
                    text="先读取文件。",
                    tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"path": "README.md"})],
                )
            return AgentResponse(text="读取完成。")

    (tmp_path / "README.md").write_text("hello\nworld\n", encoding="utf-8")
    runtime = build_runtime(tmp_path)
    runtime.provider = ToolProvider()
    runtime.provider_factory = ToolProvider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    runtime.run_turn("读取 README.md")

    assistant_messages = [m for m in runtime.session.messages if m.role == "assistant"]
    tool_messages = [m for m in runtime.session.messages if m.role == "tool"]
    assert any(part.type == "step-start" for part in assistant_messages[0].parts)
    assert any(part.type == "step-finish" for part in assistant_messages[0].parts)
    assert any(part.type == "tool" for part in assistant_messages[0].parts)
    assert any(part.type == "file" for part in tool_messages[0].parts)


def test_runtime_persists_prompt_and_loop_metadata(tmp_path: Path):
    runtime = build_runtime(tmp_path)

    reply = runtime.run_turn("metadata check")

    assert reply == "echo:metadata check"
    assert runtime.session.metadata["last_finish_reason"] == "stop"
    assert runtime.session.metadata["last_loop_unstable"] == "false"
    assert runtime.session.metadata["last_loop_steps"] == "1"
    assert runtime.session.metadata["last_loop_tool_calls"] == "0"
    assert runtime.session.metadata["last_prompt_notes"] is not None


def test_delegate_tool_result_creates_subtask_part(tmp_path: Path):
    class DelegateProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                from openagent.domain.messages import ToolCall

                return AgentResponse(
                    tool_calls=[ToolCall(id="call-1", name="delegate", arguments={"prompt": "create a.txt"})]
                )
            return AgentResponse(text="delegated")

    class ChildProvider(BaseProvider):
        def generate(self, messages, tools, system_prompt=None):
            return AgentResponse(text="child done")

    runtime = AgentRuntime(
        provider=DelegateProvider(),
        provider_factory=ChildProvider,
        workspace=tmp_path,
        session_manager=SessionManager(SessionStore((tmp_path / ".openagent" / "sessions"))),
        session=SessionManager(SessionStore((tmp_path / ".openagent" / "sessions"))).start(workspace=tmp_path),
        settings=Settings.from_workspace(tmp_path),
    )

    runtime.run_turn("delegate this")

    tool_message = next(message for message in runtime.session.messages if message.role == "tool" and message.name == "delegate")
    assert any(part.type == "subtask" for part in tool_message.parts)
