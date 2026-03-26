from __future__ import annotations

from pathlib import Path

from openagent.domain.messages import Message
from openagent.domain.session import Session
from openagent.session.store import SessionStore


class SessionManager:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def start(self, workspace: Path, session_id: str | None = None) -> Session:
        if session_id:
            return self.store.load(session_id)
        return self.store.create(workspace=workspace)

    def append_message(self, session: Session, message: Message) -> None:
        session.messages.append(message)
        session.touch()
        self.store.save(session)

    def replace_messages(self, session: Session, messages: list[Message]) -> None:
        session.messages = list(messages)
        session.touch()
        self.store.save(session)

    def list_sessions(self) -> list[Session]:
        return self.store.list_sessions()
