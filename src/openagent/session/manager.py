from __future__ import annotations

from pathlib import Path

from openagent.domain.messages import Message
from openagent.domain.session import Session
from openagent.session.compaction import maybe_compact
from openagent.session.prompt import PromptContext, build_prompt_context
from openagent.session.retry import retry_delay
from openagent.session.revert import revert_last_turn
from openagent.session.status import increment_retry, mark_completed, mark_degraded, mark_running, recover_if_interrupted
from openagent.session.store import SessionStore
from openagent.session.todo import add_todo, clear_todos, mark_todo_done


class SessionManager:
    def __init__(
        self,
        store: SessionStore,
        max_messages_before_compact: int = 20,
        prompt_recent_messages: int = 12,
    ) -> None:
        self.store = store
        self.max_messages_before_compact = max_messages_before_compact
        self.prompt_recent_messages = prompt_recent_messages

    def start(self, workspace: Path, session_id: str | None = None) -> Session:
        if session_id:
            session = self.store.load(session_id)
            if recover_if_interrupted(session):
                self.store.save(session)
            return session
        return self.store.create(workspace=workspace)

    def append_message(self, session: Session, message: Message, mark_running_state: bool = False) -> None:
        if mark_running_state and message.role == "user":
            mark_running(session, message.content)
        session.messages.append(message)
        session.touch()
        self.store.save(session)

    def append_turn_messages(self, session: Session, messages: list[Message]) -> None:
        session.messages.extend(messages)
        mark_completed(session)
        self.store.save(session)

    def build_prompt(self, session: Session, system_prompt: str) -> PromptContext:
        maybe_compact(session, self.max_messages_before_compact, keep_recent=self.prompt_recent_messages)
        self.store.save(session)
        return build_prompt_context(
            session,
            system_prompt,
            recent_message_limit=self.prompt_recent_messages,
        )

    def compact(self, session: Session) -> bool:
        changed = maybe_compact(
            session,
            self.max_messages_before_compact,
            keep_recent=self.prompt_recent_messages,
        )
        self.store.save(session)
        return changed

    def fail_turn(self, session: Session, error_message: str) -> None:
        mark_degraded(
            session,
            error_message=error_message,
            recovery_hint="Use /retry to rerun the last user turn or /revert to discard the incomplete turn.",
        )
        self.store.save(session)

    def revert_last_turn(self, session: Session) -> bool:
        changed = revert_last_turn(session)
        if changed:
            self.store.save(session)
        return changed

    def retry_last_turn(self, session: Session) -> str | None:
        if not session.status.last_user_message:
            return None
        increment_retry(session)
        self.store.save(session)
        return session.status.last_user_message

    def retry_delay_ms(self, session: Session) -> int:
        return retry_delay(max(session.status.retry_count, 1))

    def add_todo(self, session: Session, content: str, priority: str = "medium") -> None:
        add_todo(session, content, priority)
        self.store.save(session)

    def complete_todo(self, session: Session, index: int) -> None:
        mark_todo_done(session, index)
        self.store.save(session)

    def clear_todos(self, session: Session) -> None:
        clear_todos(session)
        session.touch()
        self.store.save(session)

    def list_sessions(self) -> list[Session]:
        return self.store.list_sessions()
