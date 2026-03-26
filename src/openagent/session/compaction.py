from __future__ import annotations

from openagent.domain.messages import Message
from openagent.domain.session import Session, SessionSummary, utc_now_iso
from openagent.session.summary import summarize_messages


def maybe_compact(session: Session, max_messages: int, keep_recent: int = 8) -> bool:
    if len(session.messages) <= max_messages:
        return False
    if len(session.messages) <= keep_recent:
        return False

    compacted = session.messages[:-keep_recent]
    summary_text = summarize_messages(compacted)
    previous_count = session.summary.compacted_message_count if session.summary else 0
    session.summary = SessionSummary(
        text=summary_text,
        compacted_message_count=previous_count + len(compacted),
        updated_at=utc_now_iso(),
    )
    session.metadata["compaction_count"] = str(int(session.metadata.get("compaction_count", "0")) + 1)
    session.touch()
    return True


def summary_message(session: Session) -> Message | None:
    if not session.summary:
        return None
    return Message(
        role="assistant",
        content=f"[Session Summary]\n{session.summary.text}",
    )
