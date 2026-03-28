import time
from pathlib import Path

from openagent.events.bus import EventBus
from openagent.session.background import BackgroundTaskManager
from openagent.session.store import SessionStore
from openagent.tools.builtin.background import BackgroundTaskTool
from openagent.domain.tools import ToolContext


def test_background_task_tool_start_get_and_list(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    manager = BackgroundTaskManager(store=store, workspace=tmp_path, event_bus=EventBus(tmp_path / "events.jsonl"))
    tool = BackgroundTaskTool(manager)
    context = ToolContext(workspace=tmp_path, session_id=session.id)

    start = tool.invoke(
        {
            "action": "start",
            "command": "python -c \"import time; time.sleep(0.2); print('bg-ok')\"",
            "title": "sleepy",
        },
        context,
    )
    assert not start.is_error
    task_id = start.metadata["task_id"]

    for _ in range(20):
        record = manager.get_task(session.id, task_id)
        if record and record.status in {"succeeded", "failed", "timed_out"}:
            break
        time.sleep(0.1)
    assert record is not None
    assert record.status == "succeeded"
    assert record.exit_code == 0
    assert "bg-ok" in (record.output_summary or "")

    get_result = tool.invoke({"action": "get", "task_id": task_id}, context)
    list_result = tool.invoke({"action": "list"}, context)
    assert task_id in get_result.content
    assert task_id in list_result.content


def test_background_task_completion_flows_back_into_session(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    manager = BackgroundTaskManager(store=store, workspace=tmp_path, event_bus=EventBus(tmp_path / "events.jsonl"))
    record = manager.start_task(
        session_id=session.id,
        command="python -c \"print('done-from-bg')\"",
        title="bg-summary",
    )
    for _ in range(20):
        session = store.load(session.id)
        if any(
            part.type == "background-task"
            and isinstance(part.content, dict)
            and part.content.get("task_id") == record.id
            and part.content.get("status") == "succeeded"
            for message in session.messages
            for part in message.parts
        ):
            break
        time.sleep(0.1)
    session = store.load(session.id)
    joined = "\n".join(message.content for message in session.messages)
    assert record.id in joined
    assert "done-from-bg" in joined
