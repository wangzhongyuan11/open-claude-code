from pathlib import Path

from openagent.domain.messages import Message
from openagent.session.manager import SessionManager
from openagent.session.store import SessionStore


def test_session_store_roundtrip(tmp_path: Path):
    store = SessionStore(tmp_path / "sessions")
    manager = SessionManager(store)
    session = manager.start(workspace=tmp_path)

    manager.append_message(session, Message(role="user", content="hello"))
    loaded = store.load(session.id)

    assert loaded.id == session.id
    assert loaded.messages[0].content == "hello"
