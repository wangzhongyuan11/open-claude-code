from __future__ import annotations

from openagent.domain.session import Session


def revert_last_turn(session: Session) -> bool:
    last_user_index = None
    for index in range(len(session.messages) - 1, -1, -1):
        if session.messages[index].role == "user":
            last_user_index = index
            break
    if last_user_index is None:
        return False
    del session.messages[last_user_index:]
    session.status.recovery_hint = "Last turn reverted. You can continue the session or use /retry to rerun the last user request."
    session.touch()
    return True
