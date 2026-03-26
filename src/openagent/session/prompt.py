from __future__ import annotations

from dataclasses import dataclass

from openagent.domain.messages import Message
from openagent.domain.session import Session
from openagent.session.compaction import summary_message
from openagent.session.todo import render_todos


@dataclass(slots=True)
class PromptContext:
    system_prompt: str
    messages: list[Message]


def build_prompt_context(
    session: Session,
    base_system_prompt: str,
    recent_message_limit: int = 12,
) -> PromptContext:
    system_sections = [base_system_prompt]
    if session.status.degraded:
        system_sections.append(
            "Recovery state:\n"
            f"- last_error: {session.status.last_error}\n"
            f"- recovery_hint: {session.status.recovery_hint}"
        )
    if session.todos:
        system_sections.append("Session todos:\n" + render_todos(session))

    prompt_messages: list[Message] = []
    summary = summary_message(session)
    if summary:
        prompt_messages.append(summary)
    prompt_messages.extend(session.messages[-recent_message_limit:])
    return PromptContext(
        system_prompt="\n\n".join(section for section in system_sections if section),
        messages=prompt_messages,
    )
