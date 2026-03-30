from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from openagent.domain.session import Session, SessionStatus, SessionSummary, SessionTodo
from openagent.session.message_v2 import deserialize_message, serialize_message


class SessionStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def create(self, workspace: Path, session_id: str | None = None) -> Session:
        session = Session(
            id=session_id or self._new_id(),
            workspace=str(workspace.resolve()),
            directory=str(workspace.resolve()),
        )
        self.save(session)
        return session

    def load(self, session_id: str) -> Session:
        path = self._session_file(session_id)
        if not path.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        with self.lock(session_id):
            payload = json.loads(path.read_text(encoding="utf-8"))
            return self._deserialize(payload)

    def save(self, session: Session) -> None:
        session_dir = self.root_dir / session.id
        session_dir.mkdir(parents=True, exist_ok=True)
        path = self._session_file(session.id)
        tmp_path = path.with_suffix(".json.tmp")
        payload = json.dumps(self._serialize(session), ensure_ascii=False, indent=2)
        with self.lock(session.id):
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(path)

    def list_sessions(self) -> list[Session]:
        sessions: list[Session] = []
        for path in sorted(self.root_dir.glob("*/session.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            sessions.append(self._deserialize(payload))
        return sessions

    def _session_file(self, session_id: str) -> Path:
        return self.root_dir / session_id / "session.json"

    def session_dir(self, session_id: str) -> Path:
        path = self.root_dir / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def lock(self, session_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[session_id] = lock
            return lock

    def update(self, session_id: str, updater) -> Session:
        with self.lock(session_id):
            session = self.load(session_id)
            updater(session)
            self.save(session)
            return session

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _serialize(session: Session) -> dict:
        return {
            "id": session.id,
            "schema_version": session.schema_version,
            "workspace": session.workspace,
            "project_id": session.project_id,
            "directory": session.directory,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "metadata": session.metadata,
            "permission": session.permission,
            "summary": {
                "text": session.summary.text,
                "compacted_message_count": session.summary.compacted_message_count,
                "updated_at": session.summary.updated_at,
            }
            if session.summary
            else None,
            "status": {
                "state": session.status.state,
                "retry_count": session.status.retry_count,
                "last_error": session.status.last_error,
                "recovery_hint": session.status.recovery_hint,
                "last_user_message": session.status.last_user_message,
                "last_turn_started_at": session.status.last_turn_started_at,
                "last_turn_completed_at": session.status.last_turn_completed_at,
                "degraded": session.status.degraded,
            },
            "todos": [
                {
                    "content": todo.content,
                    "status": todo.status,
                    "priority": todo.priority,
                    "source": todo.source,
                    "key": todo.key,
                }
                for todo in session.todos
            ],
            "messages": [serialize_message(message) for message in session.messages],
        }

    @staticmethod
    def _deserialize(payload: dict) -> Session:
        return Session(
            id=payload["id"],
            workspace=payload["workspace"],
            project_id=payload.get("project_id"),
            directory=payload.get("directory", payload.get("workspace")),
            title=payload.get("title"),
            schema_version=payload.get("schema_version", 1),
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            metadata=payload.get("metadata", {}),
            permission=payload.get("permission", {}),
            summary=SessionSummary(
                text=payload["summary"]["text"],
                compacted_message_count=payload["summary"]["compacted_message_count"],
                updated_at=payload["summary"].get("updated_at", payload["updated_at"]),
            )
            if payload.get("summary")
            else None,
            status=SessionStatus(
                state=payload.get("status", {}).get("state", "idle"),
                retry_count=payload.get("status", {}).get("retry_count", 0),
                last_error=payload.get("status", {}).get("last_error"),
                recovery_hint=payload.get("status", {}).get("recovery_hint"),
                last_user_message=payload.get("status", {}).get("last_user_message"),
                last_turn_started_at=payload.get("status", {}).get("last_turn_started_at"),
                last_turn_completed_at=payload.get("status", {}).get("last_turn_completed_at"),
                degraded=payload.get("status", {}).get("degraded", False),
            ),
            todos=[
                SessionTodo(
                    content=item["content"],
                    status=item.get("status", "pending"),
                    priority=item.get("priority", "medium"),
                    source=item.get("source", "manual"),
                    key=item.get("key"),
                )
                for item in payload.get("todos", [])
            ],
            messages=[deserialize_message(item) for item in payload.get("messages", [])],
        )
