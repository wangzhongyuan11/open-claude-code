from pathlib import Path

from openagent.domain.tools import ToolExecutionResult
from openagent.domain.tools import ToolContext
from openagent.session.snapshot import SnapshotManager
from openagent.session.store import SessionStore
from openagent.tools.builtin.bash import BashTool
from openagent.tools.builtin.files import WriteFileTool
from openagent.tools.registry import ToolRegistry


def _build_snapshot_manager(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    manager = SnapshotManager(store, tmp_path, enabled=True)
    return store, session, manager


def test_snapshot_revert_single_modified_file(tmp_path: Path):
    store, session, manager = _build_snapshot_manager(tmp_path)
    target = tmp_path / "a.txt"
    target.write_text("before\n", encoding="utf-8")

    record = manager.track_operation(
        session_id=session.id,
        tool_name="write_file",
        agent_name="build",
        message_id="m1",
        tool_call_id="c1",
        task_id=None,
        paths=["a.txt"],
    )
    target.write_text("after\n", encoding="utf-8")
    manager.finalize_operation(snapshot_id=record.id if record else None, result=WriteFileTool().invoke({"path": "a.txt", "content": "after\n"}, ToolContext(workspace=tmp_path)))
    manager.revert_snapshot(record.id)

    assert target.read_text(encoding="utf-8") == "before\n"


def test_snapshot_revert_newly_created_file(tmp_path: Path):
    _store, session, manager = _build_snapshot_manager(tmp_path)
    target = tmp_path / "new.txt"

    record = manager.track_operation(
        session_id=session.id,
        tool_name="write_file",
        agent_name="build",
        message_id="m1",
        tool_call_id="c1",
        task_id=None,
        paths=["new.txt"],
    )
    target.write_text("hello\n", encoding="utf-8")
    manager.finalize_operation(
        snapshot_id=record.id if record else None,
        result=WriteFileTool().invoke({"path": "new.txt", "content": "hello\n"}, ToolContext(workspace=tmp_path)),
    )
    manager.revert_snapshot(record.id)

    assert not target.exists()


def test_snapshot_revert_deleted_file(tmp_path: Path):
    _store, session, manager = _build_snapshot_manager(tmp_path)
    target = tmp_path / "gone.txt"
    target.write_text("keep\n", encoding="utf-8")

    record = manager.track_operation(
        session_id=session.id,
        tool_name="manual_delete",
        agent_name="build",
        message_id="m1",
        tool_call_id="c1",
        task_id=None,
        paths=["gone.txt"],
    )
    target.unlink()
    manager.finalize_operation(
        snapshot_id=record.id if record else None,
        result=ToolExecutionResult.success("deleted", metadata={"path": "gone.txt"}),
    )
    manager.revert_snapshot(record.id)

    assert target.read_text(encoding="utf-8") == "keep\n"


def test_snapshot_revert_specific_file_only(tmp_path: Path):
    _store, session, manager = _build_snapshot_manager(tmp_path)
    (tmp_path / "a.txt").write_text("A0\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("B0\n", encoding="utf-8")

    record = manager.track_operation(
        session_id=session.id,
        tool_name="batch",
        agent_name="build",
        message_id="m1",
        tool_call_id="c1",
        task_id=None,
        paths=["a.txt", "b.txt"],
    )
    (tmp_path / "a.txt").write_text("A1\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("B1\n", encoding="utf-8")
    manager.finalize_operation(
        snapshot_id=record.id if record else None,
        result=ToolExecutionResult.success("batch", metadata={"snapshot_changed_files": ["a.txt", "b.txt"]}),
    )
    manager.revert_snapshot(record.id, files=["a.txt"])

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "A0\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "B1\n"


def test_snapshot_revert_task_rewinds_multiple_writes(tmp_path: Path):
    _store, session, manager = _build_snapshot_manager(tmp_path)
    (tmp_path / "a.txt").write_text("v1\n", encoding="utf-8")

    snap1 = manager.track_operation(
        session_id=session.id,
        tool_name="write_file",
        agent_name="build",
        message_id="m1",
        tool_call_id="c1",
        task_id="task-1",
        paths=["a.txt"],
    )
    (tmp_path / "a.txt").write_text("v2\n", encoding="utf-8")
    manager.finalize_operation(snapshot_id=snap1.id if snap1 else None, result=ToolExecutionResult.success("ok", metadata={"path": "a.txt"}))

    snap2 = manager.track_operation(
        session_id=session.id,
        tool_name="write_file",
        agent_name="build",
        message_id="m1",
        tool_call_id="c2",
        task_id="task-1",
        paths=["a.txt", "b.txt"],
    )
    (tmp_path / "a.txt").write_text("v3\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("new\n", encoding="utf-8")
    manager.finalize_operation(
        snapshot_id=snap2.id if snap2 else None,
        result=ToolExecutionResult.success("ok", metadata={"snapshot_changed_files": ["a.txt", "b.txt"]}),
    )

    manager.revert_task(session.id, "task-1")

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "v1\n"
    assert not (tmp_path / "b.txt").exists()


def test_registry_tracks_snapshot_before_write(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    manager = SnapshotManager(store, tmp_path, enabled=True)
    registry = ToolRegistry(snapshot_manager=manager)
    registry.register(WriteFileTool())
    context = ToolContext(workspace=tmp_path, session_id=session.id, message_id="m1", tool_call_id="c1", agent_name="build")

    result = registry.invoke("write_file", {"path": "tracked.txt", "content": "hello"}, context)

    assert result.metadata["snapshot_id"].startswith(f"{session.id}:")
    records = manager.list_snapshots(session.id)
    assert len(records) == 1
    assert records[0].changed_files == ["tracked.txt"]


def test_snapshot_disabled_does_not_add_snapshot_metadata(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    manager = SnapshotManager(store, tmp_path, enabled=False)
    registry = ToolRegistry(snapshot_manager=manager)
    registry.register(WriteFileTool())
    context = ToolContext(workspace=tmp_path, session_id=session.id, message_id="m1", tool_call_id="c1", agent_name="build")

    result = registry.invoke("write_file", {"path": "plain.txt", "content": "hello"}, context)

    assert "snapshot_id" not in result.metadata
    assert manager.list_snapshots(session.id) == []


def test_registry_tracks_git_snapshot_for_bash_workspace_mutation(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create(tmp_path)
    manager = SnapshotManager(store, tmp_path, enabled=True)
    registry = ToolRegistry(snapshot_manager=manager)
    registry.register(BashTool())
    context = ToolContext(workspace=tmp_path, session_id=session.id, message_id="m1", tool_call_id="c1", agent_name="build")

    result = registry.invoke("bash", {"command": "printf 'x\\n' > bash.txt"}, context)

    assert result.metadata["snapshot_id"].startswith(f"{session.id}:")
    assert result.metadata["snapshot_changed_files"] == ["bash.txt"]
    manager.revert_snapshot(result.metadata["snapshot_id"])
    assert not (tmp_path / "bash.txt").exists()
