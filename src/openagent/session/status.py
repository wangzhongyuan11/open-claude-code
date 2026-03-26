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
    session.touch()


def mark_degraded(session: Session, error_message: str, recovery_hint: str) -> None:
    session.status.state = "degraded"
    session.status.last_error = error_message
    session.status.recovery_hint = recovery_hint
    session.status.last_turn_completed_at = utc_now_iso()
    session.status.degraded = True
    session.touch()


def increment_retry(session: Session) -> None:
    session.status.retry_count += 1
    session.status.state = "retry"
    session.touch()
