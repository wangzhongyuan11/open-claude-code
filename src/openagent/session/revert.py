from __future__ import annotations

from openagent.domain.messages import Message, Part
from openagent.domain.session import Session, utc_now_iso


def revert_last_turn(session: Session) -> bool:
    removed_messages: list[Message] = []
    last_user_index = None
    for index in range(len(session.messages) - 1, -1, -1):
        if session.messages[index].role == "user":
            last_user_index = index
            break
    if last_user_index is None:
        return False
    removed_messages = session.messages[last_user_index:]
    del session.messages[last_user_index:]
    session.status.recovery_hint = "Last turn reverted. You can continue the session or use /retry to rerun the last user request."
    session.metadata["last_revert_at"] = utc_now_iso()
    session.metadata["last_reverted_message_count"] = str(len(removed_messages))
    session.messages.append(build_revert_message(removed_messages))
    session.touch()
    return True


def build_revert_message(removed_messages: list[Message]) -> Message:
    return Message(
        role="assistant",
        agent="session-op",
        content=f"[Revert] removed {len(removed_messages)} messages from the last turn.",
        finish="stop",
        parts=[
            Part(
                type="snapshot",
                content={
                    "removed_message_ids": [message.id for message in removed_messages],
                    "removed_roles": [message.role for message in removed_messages],
                },
                state={"status": "reverted"},
            )
        ],
    )
