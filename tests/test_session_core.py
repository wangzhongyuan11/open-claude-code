from pathlib import Path

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
    manager = SessionManager(
        SessionStore(settings.session_root),
        max_messages_before_compact=settings.compact_max_messages,
        prompt_recent_messages=settings.prompt_recent_messages,
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
