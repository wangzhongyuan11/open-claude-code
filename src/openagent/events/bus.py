from __future__ import annotations

import json
from pathlib import Path

from openagent.domain.events import Event


class EventBus:
    def __init__(self, log_file: Path) -> None:
        self.log_file = log_file.resolve()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: Event) -> None:
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": event.type,
                        "timestamp": event.timestamp,
                        "payload": event.payload,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
