from __future__ import annotations

import argparse
from pathlib import Path

from openagent.events.bus import EventBus
from openagent.session.background import BackgroundTaskManager
from openagent.session.store import SessionStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenAgent background task worker")
    parser.add_argument("--session-root", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--event-log", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    store = SessionStore(Path(args.session_root))
    event_bus = EventBus(Path(args.event_log)) if args.event_log else None
    manager = BackgroundTaskManager(store=store, workspace=Path(args.workspace), event_bus=event_bus)
    manager.run_task_by_id(args.session_id, args.task_id)


if __name__ == "__main__":
    main()
