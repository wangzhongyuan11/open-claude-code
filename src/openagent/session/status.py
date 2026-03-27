from __future__ import annotations

from openagent.domain.session import Session, SessionStatus, utc_now_iso


def recover_if_interrupted(session: Session) -> bool:
    if session.status.state != "running":
        return False
    session.status = SessionStatus(
        state="degraded",
        retry_count=session.status.retry_count,
        last_error="Previous run appears to have been interrupted.",
        recovery_hint="Use /status to inspect the session, /retry to rerun the last user turn, or /revert to remove the incomplete turn.",
        last_user_message=session.status.last_user_message,
        last_turn_started_at=session.status.last_turn_started_at,
        last_turn_completed_at=session.status.last_turn_completed_at,
        degraded=True,
    )
    session.touch()
    return True


def mark_running(session: Session, user_text: str) -> None:
    session.status.state = "running"
    session.status.last_error = None
    session.status.recovery_hint = None
    session.status.last_user_message = user_text
    session.status.last_turn_started_at = utc_now_iso()
    session.status.degraded = False
    session.touch()


def mark_completed(session: Session) -> None:
    session.status.state = "idle"
    session.status.last_error = None
    session.status.recovery_hint = None
    session.status.last_turn_completed_at = utc_now_iso()
    session.status.degraded = False
    session.metadata["status_last_transition"] = "completed"
    session.touch()


def mark_degraded(session: Session, error_message: str, recovery_hint: str) -> None:
    session.status.state = "degraded"
    session.status.last_error = error_message
    session.status.recovery_hint = recovery_hint
    session.status.last_turn_completed_at = utc_now_iso()
    session.status.degraded = True
    session.metadata["status_last_transition"] = "degraded"
    session.touch()


def increment_retry(session: Session) -> None:
    session.status.retry_count += 1
    session.status.state = "retry"
    session.metadata["status_last_transition"] = "retry"
    session.metadata["last_retry_at"] = utc_now_iso()
    session.touch()


def status_payload(session: Session) -> dict[str, str | int | bool | None]:
    return {
        "state": session.status.state,
        "retry_count": session.status.retry_count,
        "last_error": session.status.last_error,
        "recovery_hint": session.status.recovery_hint,
        "last_user_message": session.status.last_user_message,
        "last_turn_started_at": session.status.last_turn_started_at,
        "last_turn_completed_at": session.status.last_turn_completed_at,
        "degraded": session.status.degraded,
        "status_last_transition": session.metadata.get("status_last_transition"),
        "last_retry_at": session.metadata.get("last_retry_at"),
        "last_revert_at": session.metadata.get("last_revert_at"),
    }


def render_status(session: Session) -> str:
    payload = status_payload(session)
    lines = [
        f"state={payload['state']}",
        f"retry_count={payload['retry_count']}",
        f"degraded={payload['degraded']}",
    ]
    if payload["last_error"]:
        lines.append(f"last_error={payload['last_error']}")
    if payload["recovery_hint"]:
        lines.append(f"recovery_hint={payload['recovery_hint']}")
    if payload["status_last_transition"]:
        lines.append(f"status_last_transition={payload['status_last_transition']}")
    if payload["last_retry_at"]:
        lines.append(f"last_retry_at={payload['last_retry_at']}")
    if payload["last_revert_at"]:
        lines.append(f"last_revert_at={payload['last_revert_at']}")
    return "\n".join(lines)
