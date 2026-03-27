from __future__ import annotations

from openagent.domain.messages import Message, Part


RETRY_INITIAL_DELAY_MS = 500
RETRY_BACKOFF_FACTOR = 2


def retry_delay(attempt: int) -> int:
    return RETRY_INITIAL_DELAY_MS * (RETRY_BACKOFF_FACTOR ** max(attempt - 1, 0))


def build_retry_message(attempt: int, last_user_message: str) -> Message:
    return Message(
        role="assistant",
        agent="session-op",
        content=f"[Retry] attempt {attempt} for: {last_user_message}",
        finish="stop",
        parts=[
            Part(
                type="retry",
                content={
                    "attempt": attempt,
                    "last_user_message": last_user_message,
                    "delay_ms": retry_delay(max(attempt, 1)),
                },
                state={"status": "scheduled"},
            )
        ],
    )
