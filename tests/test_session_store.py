from pathlib import Path

from openagent.domain.messages import Message, Part
from openagent.session.manager import SessionManager
from openagent.session.message_v2 import deserialize_message, serialize_message
from openagent.session.store import SessionStore


def test_session_store_roundtrip(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    manager = SessionManager(store)
    session = manager.start(workspace=tmp_path)

    manager.append_message(session, Message(role="user", content="hello"))
    loaded = store.load(session.id)

    assert loaded.id == session.id
    assert loaded.messages[0].content == "hello"
    assert loaded.messages[0].session_id == session.id


def test_message_v2_roundtrip_preserves_parts_and_metadata():
    message = Message(
        role="assistant",
        content="done",
        parent_id="user-1",
        agent="main",
        finish="stop",
        parts=[
            Part(type="reasoning", content="inspect file"),
            Part(type="tool", content={"name": "read_file", "arguments": {"path": "a.py"}}, state={"status": "requested"}),
            Part(type="text", content="done"),
        ],
    )

    payload = serialize_message(message)
    restored = deserialize_message(payload)

    assert restored.parent_id == "user-1"
    assert restored.agent == "main"
    assert restored.finish == "stop"
    assert [part.type for part in restored.parts] == ["reasoning", "tool", "text"]
