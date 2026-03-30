from __future__ import annotations

from pathlib import Path
from typing import Callable

from openagent.domain.messages import Message
from openagent.domain.session import Session
from openagent.session.compaction import apply_compaction_with_summary, maybe_compact, plan_compaction
from openagent.session.prompt import PromptContext, build_prompt_context
from openagent.session.retry import build_retry_message, retry_delay
from openagent.session.revert import revert_last_turn
from openagent.session.status import increment_retry, mark_completed, mark_degraded, mark_running, recover_if_interrupted
from openagent.session.store import SessionStore
from openagent.session.task_validation import MultiStepRequirements
from openagent.session.todo import (
    add_todo,
    clear_todos,
    mark_todo_done,
    sync_auto_checklist,
    sync_auto_checklist_progress,
)


class SessionManager:
    def __init__(
        self,
        store: SessionStore,
        max_messages_before_compact: int = 20,
        prompt_recent_messages: int = 12,
        prompt_max_tokens: int = 12_000,
    ) -> None:
        self.store = store
        self.max_messages_before_compact = max_messages_before_compact
        self.prompt_recent_messages = prompt_recent_messages
        self.prompt_max_tokens = prompt_max_tokens
        self.title_generator: Callable[[Session, str], str | None] | None = None
        self.compaction_summarizer: Callable[[Session, list[Message]], str | None] | None = None

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
        self._normalize_message(session, message)
        self._assign_title(session, message)
        session.messages.append(message)
        session.touch()
        self.store.save(session)

    def append_turn_messages(self, session: Session, messages: list[Message]) -> None:
        current_user_id = self._last_message_id(session, "user")
        current_assistant_id: str | None = None
        for message in messages:
            self._normalize_message(session, message)
            if message.role == "assistant":
                if message.parent_id is None:
                    message.parent_id = current_user_id
                current_assistant_id = message.id
            elif message.role == "tool" and message.parent_id is None:
                message.parent_id = current_assistant_id
            elif message.role == "user":
                current_user_id = message.id
        session.messages.extend(messages)
        mark_completed(session)
        self.store.save(session)

    def build_prompt(self, session: Session, system_prompt: str) -> PromptContext:
        plan = plan_compaction(
            session,
            self.max_messages_before_compact,
            keep_recent=self.prompt_recent_messages,
            max_prompt_tokens=self.prompt_max_tokens,
        )
        summary_text = None
        if plan.changed and self.compaction_summarizer is not None:
            summary_text = self.compaction_summarizer(session, plan.compacted_messages)
        apply_compaction_with_summary(session, plan, summary_text)
        prompt_context = build_prompt_context(session, system_prompt, plan)
        prompt_notes = plan_to_prompt_notes(plan) + prompt_context.notes
        session.metadata["last_prompt_notes"] = "|".join(prompt_notes)
        session.metadata["last_prompt_message_count"] = str(len(plan.recent_messages))
        session.metadata["last_prompt_message_ids"] = ",".join(message.id for message in plan.recent_messages[-12:])
        session.metadata["prompt_token_estimate"] = str(prompt_context.estimated_tokens)
        self.store.save(session)
        return prompt_context

    def compact(self, session: Session) -> bool:
        summary_text = None
        plan = plan_compaction(
            session,
            self.max_messages_before_compact,
            keep_recent=self.prompt_recent_messages,
            max_prompt_tokens=self.prompt_max_tokens,
        )
        if plan.changed and self.compaction_summarizer is not None:
            summary_text = self.compaction_summarizer(session, plan.compacted_messages)
        changed = maybe_compact(
            session,
            self.max_messages_before_compact,
            keep_recent=self.prompt_recent_messages,
            max_prompt_tokens=self.prompt_max_tokens,
            summary_text=summary_text,
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
        session.messages.append(
            build_retry_message(
                attempt=session.status.retry_count,
                last_user_message=session.status.last_user_message,
            )
        )
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

    def sync_checklist(self, session: Session, requirements: MultiStepRequirements) -> None:
        sync_auto_checklist(session, requirements)
        self.store.save(session)

    def sync_checklist_progress(self, session: Session, requirements: MultiStepRequirements) -> None:
        sync_auto_checklist_progress(session, requirements)
        self.store.save(session)

    def list_sessions(self) -> list[Session]:
        return self.store.list_sessions()

    def set_title_generator(self, generator: Callable[[Session, str], str | None] | None) -> None:
        self.title_generator = generator

    def set_compaction_summarizer(
        self,
        summarizer: Callable[[Session, list[Message]], str | None] | None,
    ) -> None:
        self.compaction_summarizer = summarizer

    @staticmethod
    def _normalize_message(session: Session, message: Message) -> None:
        if message.session_id is None:
            message.session_id = session.id
        if message.agent is None and message.role in {"user", "assistant"}:
            message.agent = "main"

    def _assign_title(self, session: Session, message: Message) -> None:
        if session.title or message.role != "user":
            return
        title: str | None = None
        if self.title_generator is not None:
            title = self.title_generator(session, message.content)
        if not title:
            title = message.content.strip().replace("\n", " ")
        session.title = (title[:77] + "...") if len(title) > 80 else title

    @staticmethod
    def _last_message_id(session: Session, role: str) -> str | None:
        for message in reversed(session.messages):
            if message.role == role:
                return message.id
        return None


def plan_to_prompt_notes(plan) -> list[str]:
    notes: list[str] = []
    if plan.changed:
        notes.append("compacted")
    if plan.overflow_by_count:
        notes.append("overflow:message-count")
    if plan.overflow_by_tokens:
        notes.append("overflow:token-budget")
    if plan.recent_tools:
        notes.append("recent-tools:" + ",".join(plan.recent_tools[:4]))
    if plan.recent_files:
        notes.append("recent-files:" + ",".join(plan.recent_files[:4]))
    return notes
