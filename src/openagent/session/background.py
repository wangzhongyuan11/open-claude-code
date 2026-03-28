from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from openagent.domain.events import Event, utc_now_iso
from openagent.domain.messages import Message, Part
from openagent.events.bus import EventBus
from openagent.session.store import SessionStore


@dataclass(slots=True)
class BackgroundTaskRecord:
    id: str
    session_id: str
    command: str
    title: str
    cwd: str
    status: str = "pending"
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str | None = None
    completed_at: str | None = None
    exit_code: int | None = None
    output_summary: str = ""
    error: str | None = None
    output_path: str | None = None
    timeout_seconds: int | None = None


class BackgroundTaskManager:
    def __init__(self, store: SessionStore, workspace: Path, event_bus: EventBus | None = None) -> None:
        self.store = store
        self.workspace = workspace.resolve()
        self.event_bus = event_bus

    def start_task(
        self,
        *,
        session_id: str,
        command: str,
        title: str | None = None,
        cwd: str | None = None,
        timeout_seconds: int | None = None,
    ) -> BackgroundTaskRecord:
        task_id = uuid.uuid4().hex[:12]
        cwd_path = str(self._resolve_cwd(cwd))
        record = BackgroundTaskRecord(
            id=task_id,
            session_id=session_id,
            command=command,
            title=title or command[:80],
            cwd=cwd_path,
            timeout_seconds=timeout_seconds,
        )
        self._save_task(record)
        self._append_session_message(
            session_id,
            Message(
                role="assistant",
                agent="session-op",
                content=f"[BackgroundTask] started {record.title} ({record.id})",
                finish="stop",
                parts=[
                    Part(
                        type="background-task",
                        content={
                            "task_id": record.id,
                            "title": record.title,
                            "command": record.command,
                            "cwd": record.cwd,
                            "status": "pending",
                        },
                        state={"status": "pending"},
                    )
                ],
            ),
        )
        self._spawn_worker(record)
        return record

    def get_task(self, session_id: str, task_id: str) -> BackgroundTaskRecord | None:
        return next((task for task in self.list_tasks(session_id) if task.id == task_id), None)

    def list_tasks(self, session_id: str) -> list[BackgroundTaskRecord]:
        path = self._tasks_file(session_id)
        if not path.exists():
            return []
        with self.store.lock(session_id):
            payload = json.loads(path.read_text(encoding="utf-8"))
        return [BackgroundTaskRecord(**item) for item in payload]

    def run_task_by_id(self, session_id: str, task_id: str) -> None:
        initial = self.get_task(session_id, task_id)
        if initial is None:
            raise KeyError(f"background task not found: {task_id}")
        self._update_task(session_id, initial.id, status="running", started_at=utc_now_iso())
        self._emit("background_task.running", {"session_id": session_id, "task_id": initial.id, "title": initial.title})
        try:
            completed = subprocess.run(
                initial.command,
                shell=True,
                cwd=initial.cwd,
                capture_output=True,
                text=True,
                timeout=initial.timeout_seconds,
            )
            combined = (completed.stdout + completed.stderr).strip()
            output_path = self._write_output(session_id, initial.id, combined)
            summary = self._summarize_output(combined)
            error = None if completed.returncode == 0 else summary or f"exit_code={completed.returncode}"
            updated = self._update_task(
                session_id,
                initial.id,
                status="succeeded" if completed.returncode == 0 else "failed",
                completed_at=utc_now_iso(),
                exit_code=completed.returncode,
                output_summary=summary,
                error=error,
                output_path=str(output_path),
            )
        except subprocess.TimeoutExpired as exc:
            combined = (exc.stdout or "") + (exc.stderr or "")
            output_path = self._write_output(session_id, initial.id, combined)
            updated = self._update_task(
                session_id,
                initial.id,
                status="timed_out",
                completed_at=utc_now_iso(),
                exit_code=None,
                output_summary=self._summarize_output(combined),
                error=f"timed out after {initial.timeout_seconds}s" if initial.timeout_seconds else "timed out",
                output_path=str(output_path),
            )
        self._append_completion_message(updated)
        self._emit(
            "background_task.completed",
            {
                "session_id": session_id,
                "task_id": updated.id,
                "status": updated.status,
                "exit_code": updated.exit_code,
            },
        )

    def _spawn_worker(self, record: BackgroundTaskRecord) -> None:
        env = dict(os.environ)
        repo_src = str(Path(__file__).resolve().parents[2])
        existing_pythonpath = env.get("PYTHONPATH", "")
        pythonpath_parts = [repo_src]
        if existing_pythonpath:
            pythonpath_parts.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
        args = [
            sys.executable,
            "-m",
            "openagent.session.background_worker",
            "--session-root",
            str(self.store.root_dir),
            "--workspace",
            str(self.workspace),
            "--session-id",
            record.session_id,
            "--task-id",
            record.id,
        ]
        if self.event_bus is not None:
            args.extend(["--event-log", str(self.event_bus.log_file)])
        subprocess.Popen(
            args,
            cwd=self.workspace,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _append_completion_message(self, record: BackgroundTaskRecord) -> None:
        status_line = f"status={record.status}"
        exit_line = f"exit_code={record.exit_code}" if record.exit_code is not None else "exit_code=(none)"
        text = "\n".join(
            [
                f"[BackgroundTask] {record.title} ({record.id})",
                status_line,
                exit_line,
                f"summary: {record.output_summary or '(no output)'}",
                f"error: {record.error or '(none)'}",
            ]
        )
        self._append_session_message(
            record.session_id,
            Message(
                role="assistant",
                agent="session-op",
                content=text,
                finish="stop",
                parts=[
                    Part(
                        type="background-task",
                        content={
                            "task_id": record.id,
                            "title": record.title,
                            "command": record.command,
                            "cwd": record.cwd,
                            "status": record.status,
                            "exit_code": record.exit_code,
                            "output_summary": record.output_summary,
                            "error": record.error,
                            "output_path": record.output_path,
                        },
                        state={"status": record.status},
                    )
                ],
            ),
        )

    def _append_session_message(self, session_id: str, message: Message) -> None:
        def updater(session):
            message.session_id = session.id
            session.messages.append(message)
            session.metadata["background_task_last_update"] = utc_now_iso()
            session.touch()

        self.store.update(session_id, updater)

    def _save_task(self, record: BackgroundTaskRecord) -> None:
        tasks = self.list_tasks(record.session_id)
        tasks.append(record)
        self._write_tasks(record.session_id, tasks)

    def _update_task(self, session_id: str, task_id: str, **changes) -> BackgroundTaskRecord:
        tasks = self.list_tasks(session_id)
        updated: BackgroundTaskRecord | None = None
        for task in tasks:
            if task.id == task_id:
                for key, value in changes.items():
                    setattr(task, key, value)
                updated = task
                break
        if updated is None:
            raise KeyError(f"background task not found: {task_id}")
        self._write_tasks(session_id, tasks)
        return updated

    def _write_tasks(self, session_id: str, tasks: list[BackgroundTaskRecord]) -> None:
        path = self._tasks_file(session_id)
        tmp = path.with_suffix(".tmp")
        payload = json.dumps([asdict(task) for task in tasks], ensure_ascii=False, indent=2)
        with self.store.lock(session_id):
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)

    def _tasks_file(self, session_id: str) -> Path:
        return self.store.session_dir(session_id) / "background_tasks.json"

    def _outputs_dir(self, session_id: str) -> Path:
        path = self.store.session_dir(session_id) / "background_outputs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_output(self, session_id: str, task_id: str, output: str) -> Path:
        path = self._outputs_dir(session_id) / f"{task_id}.log"
        path.write_text(output or "", encoding="utf-8")
        return path

    def _resolve_cwd(self, cwd: str | None) -> Path:
        if not cwd:
            return self.workspace
        path = (self.workspace / cwd).resolve()
        if self.workspace != path and self.workspace not in path.parents:
            raise ValueError(f"cwd escapes workspace: {cwd}")
        return path

    @staticmethod
    def _summarize_output(output: str, max_chars: int = 600) -> str:
        output = output.strip()
        if not output:
            return ""
        if len(output) <= max_chars:
            return output
        return output[:max_chars] + f"\n...[truncated {len(output) - max_chars} chars]"

    def _emit(self, event_type: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event(type=event_type, payload=payload))
