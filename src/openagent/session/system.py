from __future__ import annotations

from openagent.domain.session import Session


def build_system_prompt(session: Session, base_system_prompt: str) -> str:
    sections: list[str] = [base_system_prompt]
    context_lines = [
        f"session_id: {session.id}",
        f"directory: {session.directory or session.workspace}",
    ]
    if session.title:
        context_lines.append(f"title: {session.title}")
    if session.summary:
        context_lines.append(
            f"compacted_messages: {session.summary.compacted_message_count}"
        )
    sections.append("Session context:\n" + "\n".join(f"- {line}" for line in context_lines))
    if session.status.degraded:
        sections.append(
            "Recovery state:\n"
            f"- last_error: {session.status.last_error}\n"
            f"- recovery_hint: {session.status.recovery_hint}"
        )
    return "\n\n".join(section for section in sections if section.strip())
