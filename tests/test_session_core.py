from pathlib import Path
import json
import sys

from openagent.agent.loop import AgentLoop
from openagent.agent.runtime import AgentRuntime, build_default_runtime
from openagent.config.settings import Settings
from openagent.domain.messages import AgentResponse, Message
from openagent.domain.session import SessionStatus
from openagent.session.status import render_status
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


def _write_fake_mcp_config(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "mcp" / "fake_mcp_server.py"
    (tmp_path / "openagent.mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fake": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": [str(fixture)],
                        "enabled": True,
                        "timeout": 5,
                    }
                }
            }
        ),
        encoding="utf-8",
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
    assert loaded.todos[0].source == "manual"


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


def test_runtime_can_report_and_switch_model(tmp_path: Path):
    runtime = build_runtime(tmp_path)

    result = runtime.switch_model("test-provider/test-model")
    payload = json.loads(runtime.model_report())
    status = json.loads(runtime.status_report())

    assert result == "Switched model to `test-provider/test-model`."
    assert payload["provider"] == "test-provider"
    assert payload["model"] == "test-model"
    assert payload["source"] == "session"
    assert status["provider"] == "test-provider"
    assert status["model"] == "test-model"


def test_revert_last_turn_removes_latest_user_turn(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    runtime.run_turn("first")
    runtime.run_turn("second")

    result = runtime.revert_last_turn()

    assert result == "Reverted last turn."
    assert runtime.session.messages[-2].content == "echo:first"
    assert runtime.session.messages[-1].agent == "session-op"
    assert any(part.type == "snapshot" for part in runtime.session.messages[-1].parts)


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


def test_build_default_runtime_yolo_flag_overrides_existing_session(tmp_path: Path):
    initial = build_default_runtime(workspace=tmp_path)
    session_id = initial.session.id
    initial.session.permission["yolo"] = False
    initial.session_manager.store.save(initial.session)

    resumed = build_default_runtime(workspace=tmp_path, session_id=session_id, yolo=True)

    assert resumed.session.permission["yolo"] is True
    assert resumed.session.metadata["yolo_mode"] == "true"


def test_todo_commands_are_persisted(tmp_path: Path):
    runtime = build_runtime(tmp_path)

    runtime.add_todo("verify session", "high")
    runtime.complete_todo(0)

    assert "[completed] (high) verify session" in render_todos(runtime.session)
    assert runtime.session.metadata["todo_pending_count"] == "0"


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


def test_prompt_window_trims_large_tool_outputs(tmp_path: Path):
    runtime = build_runtime(tmp_path, compact_max_messages=2)
    large_text = "x" * 5000
    runtime.session_manager.append_message(runtime.session, Message(role="user", content="seed"))
    runtime.session_manager.append_turn_messages(
        runtime.session,
        [
            Message(role="assistant", content="", tool_calls=[]),
            Message(role="tool", content=large_text, name="read_file", tool_call_id="call-1"),
        ],
    )

    prompt = runtime.session_manager.build_prompt(runtime.session, runtime.system_prompt)

    assert any("prompt-window-trimmed:" in note for note in prompt.notes)
    assert prompt.estimated_tokens < 2000


def test_system_prompt_includes_connected_mcp_context(tmp_path: Path):
    _write_fake_mcp_config(tmp_path)
    runtime = build_runtime(tmp_path)

    prompt = runtime.system_prompt

    assert "MCP runtime:" in prompt
    assert "connected_servers: fake (1 tools)" in prompt
    assert "mcp__fake__echo" in prompt


def test_system_prompt_reports_missing_mcp_connections(tmp_path: Path):
    (tmp_path / "openagent.mcp.json").write_text(
        json.dumps({"mcpServers": {"broken": {"type": "stdio", "command": "missing-mcp-server", "enabled": True}}}),
        encoding="utf-8",
    )
    runtime = build_runtime(tmp_path)

    prompt = runtime.system_prompt

    assert "MCP runtime:" in prompt
    assert "connected_servers: none" in prompt
    assert "configured_server_status: broken=failed" in prompt


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

    inspect = runtime.inspect_session()
    replay = runtime.replay_session()
    assert '"last_finish_reason": "stop"' in inspect
    assert "Turn 1" in replay
    assert "User: metadata check" in replay


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


def test_write_file_tool_result_creates_file_mutation_part(tmp_path: Path):
    class WriteProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                from openagent.domain.messages import ToolCall

                return AgentResponse(
                    tool_calls=[ToolCall(id="call-1", name="write_file", arguments={"path": "x.txt", "content": "abc"})]
                )
            return AgentResponse(text="done")

    runtime = build_runtime(tmp_path)
    runtime.provider = WriteProvider()
    runtime.provider_factory = WriteProvider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    runtime.run_turn("write file")

    tool_message = next(message for message in runtime.session.messages if message.role == "tool" and message.name == "write_file")
    file_part = next(part for part in tool_message.parts if part.type == "file")
    assert file_part.state["mutation"] == "write_file"
    assert any(part.type == "patch" for part in tool_message.parts)
    assert any(part.type == "snapshot" for part in tool_message.parts)


def test_streaming_processor_assembles_text_deltas_and_tool_calls(tmp_path: Path):
    class StreamingProvider(BaseProvider):
        def generate(self, messages, tools, system_prompt=None):
            raise AssertionError("stream path should be used")

        def stream_generate(self, messages, tools, system_prompt=None):
            from openagent.domain.messages import AgentResponse, ToolCall

            yield {"type": "start"}
            yield {"type": "text-delta", "text": "先"}
            yield {"type": "text-delta", "text": "读取"}
            tool_call = ToolCall(id="call-1", name="read_file", arguments={"path": "README.md"})
            yield {"type": "tool-call", "tool_call": tool_call}
            yield {
                "type": "finish",
                "response": AgentResponse(
                    text="先读取",
                    tool_calls=[tool_call],
                    finish="tool-calls",
                ),
            }

    (tmp_path / "README.md").write_text("hello\nworld\n", encoding="utf-8")
    runtime = build_runtime(tmp_path)
    runtime.provider = StreamingProvider()
    runtime.provider_factory = StreamingProvider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    runtime.run_turn("streaming readme")

    assistant_message = next(message for message in runtime.session.messages if message.role == "assistant")
    assert assistant_message.content == "先读取"
    assert any(part.type == "tool" for part in assistant_message.parts)


def test_streaming_processor_assembles_reasoning_parts_and_stream_events(tmp_path: Path):
    class StreamingReasoningProvider(BaseProvider):
        def generate(self, messages, tools, system_prompt=None):
            raise AssertionError("stream path should be used")

        def stream_generate(self, messages, tools, system_prompt=None):
            yield {"type": "start"}
            yield {"type": "reasoning-delta", "text": "让我先分析"}
            yield {"type": "text-delta", "text": "结论"}
            yield {
                "type": "finish",
                "response": AgentResponse(
                    text="结论",
                    finish="stop",
                ),
            }

    runtime = build_runtime(tmp_path)
    runtime.provider = StreamingReasoningProvider()
    runtime.provider_factory = StreamingReasoningProvider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    seen: list[dict[str, str]] = []
    reply = runtime.run_turn("stream reasoning", stream_handler=lambda event: seen.append(event))

    assert reply == "结论"
    assistant_message = next(message for message in runtime.session.messages if message.role == "assistant")
    reasoning_parts = [part for part in assistant_message.parts if part.type == "reasoning"]
    assert len(reasoning_parts) == 1
    assert reasoning_parts[0].content == "让我先分析"
    assert reasoning_parts[0].state["status"] == "completed"
    assert [event["type"] for event in seen] == [
        "reasoning-start",
        "reasoning-delta",
        "reasoning-end",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]


def test_runtime_stream_handler_receives_text_deltas(tmp_path: Path):
    class StreamingEchoProvider(BaseProvider):
        def generate(self, messages, tools, system_prompt=None):
            raise AssertionError("stream path should be used")

        def stream_generate(self, messages, tools, system_prompt=None):
            yield {"type": "start"}
            yield {"type": "text-delta", "text": "stream-"}
            yield {"type": "text-delta", "text": "ok"}
            yield {
                "type": "finish",
                "response": AgentResponse(
                    text="stream-ok",
                    finish="stop",
                ),
            }

    runtime = build_runtime(tmp_path)
    runtime.provider = StreamingEchoProvider()
    runtime.provider_factory = StreamingEchoProvider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    seen: list[str] = []
    reply = runtime.run_turn(
        "stream now",
        stream_handler=lambda event: seen.append(event["text"]) if event["type"] == "text-delta" else None,
    )

    assert reply == "stream-ok"
    assert seen == ["stream-", "ok"]


def test_streaming_processor_prefers_complete_final_text_when_deltas_are_partial(tmp_path: Path):
    class PartialDeltaProvider(BaseProvider):
        def generate(self, messages, tools, system_prompt=None):
            raise AssertionError("stream path should be used")

        def stream_generate(self, messages, tools, system_prompt=None):
            yield {"type": "start"}
            yield {"type": "text-delta", "text": "："}
            yield {
                "type": "finish",
                "response": AgentResponse(
                    text="完整的最终回复",
                    finish="stop",
                ),
            }

    runtime = build_runtime(tmp_path)
    runtime.provider = PartialDeltaProvider()
    runtime.provider_factory = PartialDeltaProvider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("stream partial")

    assert reply == "完整的最终回复"
    assistant_message = next(message for message in runtime.session.messages if message.role == "assistant")
    text_part = next(part for part in assistant_message.parts if part.type == "text")
    assert text_part.content == "完整的最终回复"


def test_compaction_appends_operational_message_and_prompt_ignores_it(tmp_path: Path):
    runtime = build_runtime(tmp_path, compact_max_messages=2)
    runtime.run_turn("first")
    runtime.run_turn("second")
    runtime.run_turn("third")

    assert any(message.agent == "session-op" and any(part.type == "compaction" for part in message.parts) for message in runtime.session.messages)
    prompt = runtime.session_manager.build_prompt(runtime.session, runtime.system_prompt)
    assert all(message.agent != "session-op" for message in prompt.messages)


def test_retry_appends_retry_part_and_updates_status(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    runtime.run_turn("retry me")

    retried = runtime.session_manager.retry_last_turn(runtime.session)

    assert retried == "retry me"
    retry_message = runtime.session.messages[-1]
    assert retry_message.agent == "session-op"
    assert any(part.type == "retry" for part in retry_message.parts)
    assert runtime.session.status.state == "retry"
    assert runtime.session.metadata["status_last_transition"] == "retry"


def test_status_render_includes_transition_metadata(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    runtime.run_turn("status please")

    status_text = render_status(runtime.session)

    assert "state=idle" in status_text
    assert "status_last_transition=completed" in status_text

    status_payload = json.loads(runtime.status_report())
    assert status_payload["background_task_count"] == 0
    assert status_payload["active_background_task_count"] == 0


def test_runtime_tool_enforcement_retries_and_prevents_unverified_success(tmp_path: Path):
    class FakeCreateProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return AgentResponse(text="已创建 x.txt")
            return AgentResponse(text="仍然没有使用工具")

    runtime = build_runtime(tmp_path)
    provider = FakeCreateProvider()
    runtime.provider = provider
    runtime.provider_factory = lambda: provider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("请创建 x.txt，内容是 1。")

    assert "cannot verify" in reply
    assert provider.calls == 2


def test_runtime_tool_enforcement_retries_html_generation_without_tool(tmp_path: Path):
    class FakeHtmlProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                return AgentResponse(text="我会生成 HTML 页面。", finish="stop")
            return AgentResponse(text="仍然没有写入文件。", finish="stop")

    runtime = build_runtime(tmp_path)
    provider = FakeHtmlProvider()
    runtime.provider = provider
    runtime.provider_factory = lambda: provider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("请生成 HTML 攻略并保存到 work/guide.html")

    assert "cannot verify" in reply
    assert provider.calls == 2


def test_processor_marks_other_finish_without_tools_as_unstable(tmp_path: Path):
    class OtherFinishProvider(BaseProvider):
        def generate(self, messages, tools, system_prompt=None):
            return AgentResponse(text="我接下来会写文件。", finish="other")

    runtime = build_runtime(tmp_path)
    provider = OtherFinishProvider()
    runtime.provider = provider
    runtime.provider_factory = lambda: provider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("继续")

    assert "incomplete_model_response" in reply
    assert runtime.session.metadata["last_loop_unstable"] == "true"


def test_runtime_continues_after_incomplete_response_following_tool_result(tmp_path: Path):
    class InterruptedArtifactProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            from openagent.domain.messages import ToolCall

            if self.calls == 1:
                return AgentResponse(
                    tool_calls=[ToolCall(id="call-1", name="ensure_dir", arguments={"path": "work"})],
                    finish="tool-calls",
                )
            if self.calls == 2:
                return AgentResponse(text="：", finish="other")
            if self.calls == 3:
                assert any(message.role == "tool" and message.name == "ensure_dir" for message in messages)
                assert not any(
                    message.role == "assistant"
                    and "incomplete_model_response" in message.content
                    for message in messages
                )
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-2",
                            name="write_file",
                            arguments={"path": "work/guide.html", "content": "<!doctype html><title>guide</title>"},
                        )
                    ],
                    finish="tool-calls",
                )
            return AgentResponse(text="已生成 work/guide.html", finish="stop")

    runtime = build_runtime(tmp_path)
    provider = InterruptedArtifactProvider()
    runtime.provider = provider
    runtime.provider_factory = lambda: provider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("请生成 HTML 攻略并保存到 work/guide.html")

    assert reply == "已生成 work/guide.html"
    assert (tmp_path / "work" / "guide.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    assert provider.calls == 4
    assert runtime.session.metadata["last_loop_unstable"] == "false"
    assert runtime.session.metadata["last_loop_tool_calls"] == "2"


def test_runtime_continues_after_length_finish_for_artifact_request(tmp_path: Path):
    class LengthInterruptedProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            from openagent.domain.messages import ToolCall

            if self.calls == 1:
                return AgentResponse(text="<html", finish="length")
            if self.calls == 2:
                return AgentResponse(
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="write_file",
                            arguments={"path": "work/guide.html", "content": "<!doctype html><title>guide</title>"},
                        )
                    ],
                    finish="tool-calls",
                )
            return AgentResponse(text="已生成 work/guide.html", finish="stop")

    runtime = build_runtime(tmp_path)
    provider = LengthInterruptedProvider()
    runtime.provider = provider
    runtime.provider_factory = lambda: provider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("请生成 HTML 攻略并保存到 work/guide.html")

    assert reply == "已生成 work/guide.html"
    assert (tmp_path / "work" / "guide.html").exists()
    assert provider.calls == 3


def test_processor_stops_after_write_file_when_request_is_already_satisfied(tmp_path: Path):
    class CreateProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            from openagent.domain.messages import ToolCall

            return AgentResponse(
                tool_calls=[ToolCall(id="call-1", name="write_file", arguments={"path": "done.txt", "content": "ok"})],
                finish="tool-calls",
            )

    runtime = build_runtime(tmp_path)
    provider = CreateProvider()
    runtime.provider = provider
    runtime.provider_factory = lambda: provider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("请创建 done.txt，内容是 ok")

    assert reply == "已完成，已写入 done.txt。"
    assert provider.calls == 1


def test_tool_message_content_for_read_file_is_not_duplicated(tmp_path: Path):
    class ReadProvider(BaseProvider):
        def generate(self, messages, tools, system_prompt=None):
            from openagent.domain.messages import ToolCall

            return AgentResponse(
                tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"path": "done.txt"})],
                finish="tool-calls",
            )

    (tmp_path / "done.txt").write_text("exact-content", encoding="utf-8")
    runtime = build_runtime(tmp_path)
    provider = ReadProvider()
    runtime.provider = provider
    runtime.provider_factory = lambda: provider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("请读取 done.txt 并只回复其内容。")

    tool_message = next(message for message in runtime.session.messages if message.role == "tool")
    assert tool_message.content == "exact-content"
    assert reply == "exact-content"


def test_processor_stops_after_edit_file_when_after_content_matches_expected(tmp_path: Path):
    class EditProvider(BaseProvider):
        def generate(self, messages, tools, system_prompt=None):
            from openagent.domain.messages import ToolCall

            return AgentResponse(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="edit_file",
                        arguments={"path": "story.txt", "old_text": "第二行", "new_text": "第二行-完成"},
                    )
                ],
                finish="tool-calls",
            )

    (tmp_path / "story.txt").write_text("第一行\n第二行", encoding="utf-8")
    runtime = build_runtime(tmp_path)
    provider = EditProvider()
    runtime.provider = provider
    runtime.provider_factory = lambda: provider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("请把 story.txt 中的 第二行 改成 第二行-完成。")

    assert reply == "已完成，已修改 story.txt。"


def test_processor_stops_after_exact_read_completion(tmp_path: Path):
    class ReadProvider(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools, system_prompt=None):
            self.calls += 1
            from openagent.domain.messages import ToolCall

            return AgentResponse(
                tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"path": "done.txt"})],
                finish="tool-calls",
            )

    (tmp_path / "done.txt").write_text("exact-content", encoding="utf-8")
    runtime = build_runtime(tmp_path)
    provider = ReadProvider()
    runtime.provider = provider
    runtime.provider_factory = lambda: provider
    runtime.loop = AgentLoop(
        provider=runtime.provider,
        tool_registry=runtime.registry,
        tool_context=runtime.loop.processor.tool_context,
        event_bus=runtime.event_bus,
    )

    reply = runtime.run_turn("请读取 done.txt 并只回复其内容。")

    assert reply == "exact-content"
    assert provider.calls == 1


def test_processor_stops_after_delegate_completion(tmp_path: Path):
    class DelegateProvider(BaseProvider):
        def generate(self, messages, tools, system_prompt=None):
            from openagent.domain.messages import ToolCall

            return AgentResponse(
                tool_calls=[ToolCall(id="call-1", name="delegate", arguments={"prompt": "create a.txt"})],
                finish="tool-calls",
            )

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

    reply = runtime.run_turn("请把下面任务委托给子代理完成：创建 a.txt，内容是 1")

    assert "child done" in reply


def test_runtime_snapshot_rollback_reverts_last_file_change_and_records_session_op(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    context = runtime.loop.tool_context.child(message_id="m1", tool_call_id="c1", metadata={"tool_name": "write_file"})

    result = runtime.registry.invoke("write_file", {"path": "snap.txt", "content": "alpha"}, context)

    assert result.metadata["snapshot_id"]
    assert (tmp_path / "snap.txt").read_text(encoding="utf-8") == "alpha"

    message = runtime.rollback("last")

    assert "snap.txt" in message
    assert not (tmp_path / "snap.txt").exists()
    assert runtime.session.messages[-1].agent == "session-op"
    assert any(part.type == "snapshot" for part in runtime.session.messages[-1].parts)


def test_runtime_rollback_last_skips_noop_snapshots(tmp_path: Path):
    runtime = build_runtime(tmp_path)
    context1 = runtime.loop.tool_context.child(message_id="m1", tool_call_id="c1", metadata={"tool_name": "write_file"})
    runtime.registry.invoke("write_file", {"path": "snap.txt", "content": "alpha"}, context1)

    context2 = runtime.loop.tool_context.child(message_id="m2", tool_call_id="c2", metadata={"tool_name": "write_file"})
    runtime.registry.invoke("write_file", {"path": "snap.txt", "content": "alpha"}, context2)

    message = runtime.rollback("last")

    assert "snap.txt" in message
    assert not (tmp_path / "snap.txt").exists()
