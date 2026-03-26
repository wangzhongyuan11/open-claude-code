from __future__ import annotations


RETRY_INITIAL_DELAY_MS = 500
RETRY_BACKOFF_FACTOR = 2


def retry_delay(attempt: int) -> int:
    return RETRY_INITIAL_DELAY_MS * (RETRY_BACKOFF_FACTOR ** max(attempt - 1, 0))
