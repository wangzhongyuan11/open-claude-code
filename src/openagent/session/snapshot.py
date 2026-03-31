from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Any

from openagent.domain.events import Event
from openagent.domain.messages import Message, Part
from openagent.domain.session import utc_now_iso
from openagent.domain.tools import ToolExecutionResult
from openagent.events.bus import EventBus
from openagent.session.store import SessionStore


@dataclass(slots=True)
class SnapshotRecord:
    id: str
    session_id: str
    tool_name: str
    created_at: str
    snapshot_hash: str
    git_dir: str
    workspace: str
    agent_name: str | None = None
    message_id: str | None = None
    tool_call_id: str | None = None
    task_id: str | None = None
    status: str = "tracked"
    result_status: str | None = None
    applied_at: str | None = None
    reverted_at: str | None = None
    predicted_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    patch_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "created_at": self.created_at,
            "snapshot_hash": self.snapshot_hash,
            "git_dir": self.git_dir,
            "workspace": self.workspace,
            "agent_name": self.agent_name,
            "message_id": self.message_id,
            "tool_call_id": self.tool_call_id,
            "task_id": self.task_id,
            "status": self.status,
            "result_status": self.result_status,
            "applied_at": self.applied_at,
            "reverted_at": self.reverted_at,
            "predicted_files": self.predicted_files,
            "changed_files": self.changed_files,
            "patch_hash": self.patch_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SnapshotRecord":
        return cls(
            id=payload["id"],
            session_id=payload["session_id"],
            tool_name=payload["tool_name"],
            created_at=payload["created_at"],
            snapshot_hash=payload["snapshot_hash"],
            git_dir=payload["git_dir"],
            workspace=payload["workspace"],
            agent_name=payload.get("agent_name"),
            message_id=payload.get("message_id"),
            tool_call_id=payload.get("tool_call_id"),
            task_id=payload.get("task_id"),
            status=payload.get("status", "tracked"),
            result_status=payload.get("result_status"),
            applied_at=payload.get("applied_at"),
            reverted_at=payload.get("reverted_at"),
            predicted_files=list(payload.get("predicted_files", [])),
            changed_files=list(payload.get("changed_files", [])),
            patch_hash=payload.get("patch_hash"),
        )


@dataclass(slots=True)
class SnapshotPatch:
    snapshot_id: str
    hash: str
    files: list[str]
    diff: str
    snapshot_hash: str


@dataclass(slots=True)
class SnapshotRevertResult:
    scope: str
    snapshot_ids: list[str]
    reverted_files: list[str]
    diff: str = ""


class SnapshotManager:
    def __init__(
        self,
        store: SessionStore,
        workspace: Path,
        *,
        enabled: bool = True,
        event_bus: EventBus | None = None,
    ) -> None:
        self.store = store
        self.workspace = workspace.resolve()
        self.enabled = enabled
        self.event_bus = event_bus
        self._git_root = self.store.root_dir.parent / "snapshot"
        self._git_root.mkdir(parents=True, exist_ok=True)
        self._repo_locks: dict[str, threading.RLock] = {}
        self._repo_locks_guard = threading.Lock()

    def track_operation(
        self,
        *,
        session_id: str,
        tool_name: str,
        agent_name: str | None,
        message_id: str | None,
        tool_call_id: str | None,
        task_id: str | None,
        paths: list[str],
    ) -> SnapshotRecord | None:
        if not self.enabled or not session_id:
            return None
        unique_paths = self._normalize_paths(paths)
        snapshot_hash = self.track()
        if not snapshot_hash:
            return None
        git_dir = str(self._git_dir())
        record = SnapshotRecord(
            id=_snapshot_id(session_id, tool_call_id, tool_name, unique_paths),
            session_id=session_id,
            tool_name=tool_name,
            created_at=utc_now_iso(),
            snapshot_hash=snapshot_hash,
            git_dir=git_dir,
            workspace=str(self.workspace),
            agent_name=agent_name,
            message_id=message_id,
            tool_call_id=tool_call_id,
            task_id=task_id,
            predicted_files=unique_paths,
        )
        self._save(record)
        self._emit(
            "snapshot.tracked",
            {
                "session_id": session_id,
                "snapshot_id": record.id,
                "snapshot_hash": snapshot_hash,
                "tool_name": tool_name,
                "file_count": len(unique_paths),
            },
        )
        return record

    def finalize_operation(
        self,
        *,
        snapshot_id: str | None,
        result: ToolExecutionResult,
    ) -> SnapshotRecord | None:
        if not self.enabled or not snapshot_id:
            return None
        record = self.load(snapshot_id)
        patch = self.patch(record.id)
        record.changed_files = patch.files
        record.patch_hash = patch.hash
        record.result_status = result.status
        record.applied_at = utc_now_iso()
        if record.changed_files:
            record.status = "applied"
        elif result.is_error:
            record.status = "failed"
        else:
            record.status = "noop"
        self._save(record)
        self._emit(
            "snapshot.applied",
            {
                "session_id": record.session_id,
                "snapshot_id": record.id,
                "snapshot_hash": record.snapshot_hash,
                "tool_name": record.tool_name,
                "status": record.status,
                "changed_files": record.changed_files,
            },
        )
        return record

    def track(self) -> str | None:
        if not self.enabled:
            return None
        with self._repo_lock():
            self._ensure_repo()
            self._sync_excludes()
            self._add_workspace()
            result = self._git(["write-tree"], check=False)
            snapshot_hash = result.stdout.strip()
            if result.returncode != 0 or not snapshot_hash:
                raise RuntimeError(f"failed to create snapshot tree: {result.stderr.strip()}")
            return snapshot_hash

    def patch(self, snapshot_id: str, files: list[str] | None = None) -> SnapshotPatch:
        record = self.load(snapshot_id)
        with self._repo_lock():
            self._ensure_repo()
            self._sync_excludes()
            self._add_workspace()
            selected = self._normalize_paths(files or record.changed_files or record.predicted_files)
            diff_args = ["diff", "--cached", "--no-ext-diff", "--name-only", record.snapshot_hash, "--", "."]
            if selected:
                diff_args = ["diff", "--cached", "--no-ext-diff", "--name-only", record.snapshot_hash, "--", *selected]
            names = self._git(diff_args, check=False)
            if names.returncode != 0:
                raise RuntimeError(f"failed to compute snapshot patch: {names.stderr.strip()}")
            changed = [line.strip() for line in names.stdout.splitlines() if line.strip()]
            diff_text = self._diff_against_hash(record.snapshot_hash, files=selected or None)
            patch_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()[:12] if diff_text else "no-change"
            return SnapshotPatch(
                snapshot_id=record.id,
                hash=patch_hash,
                files=changed,
                diff=diff_text,
                snapshot_hash=record.snapshot_hash,
            )

    def diff(self, snapshot_id: str, files: list[str] | None = None) -> str:
        return self.patch(snapshot_id, files=files).diff

    def revert_snapshot(self, snapshot_id: str, files: list[str] | None = None) -> SnapshotRevertResult:
        record = self.load(snapshot_id)
        patch = self.patch(snapshot_id, files=files)
        if not patch.files:
            return SnapshotRevertResult(scope="snapshot", snapshot_ids=[record.id], reverted_files=[], diff="")
        self._revert_patch(patch)
        record.reverted_at = utc_now_iso()
        record.status = "reverted"
        self._save(record)
        self._emit(
            "snapshot.reverted",
            {
                "session_id": record.session_id,
                "snapshot_id": record.id,
                "snapshot_hash": record.snapshot_hash,
                "tool_name": record.tool_name,
                "reverted_files": patch.files,
            },
        )
        return SnapshotRevertResult(
            scope="snapshot",
            snapshot_ids=[record.id],
            reverted_files=sorted(set(patch.files)),
            diff=patch.diff,
        )

    def revert_tool_call(self, session_id: str, tool_call_id: str, files: list[str] | None = None) -> SnapshotRevertResult:
        record = self._latest_record(session_id, lambda item: item.tool_call_id == tool_call_id)
        if record is None:
            raise FileNotFoundError(f"snapshot not found for tool call: {tool_call_id}")
        return self.revert_snapshot(record.id, files=files)

    def revert_file(self, session_id: str, path: str) -> SnapshotRevertResult:
        normalized = self._normalize_path(path)
        record = self._latest_record(session_id, lambda item: normalized in item.changed_files or normalized in item.predicted_files)
        if record is None:
            raise FileNotFoundError(f"snapshot not found for file: {path}")
        return self.revert_snapshot(record.id, files=[normalized])

    def revert_task(self, session_id: str, task_id: str, files: list[str] | None = None) -> SnapshotRevertResult:
        records = [item for item in self.list_snapshots(session_id) if item.task_id == task_id]
        if not records:
            raise FileNotFoundError(f"snapshot not found for task: {task_id}")
        reverted_files: list[str] = []
        diffs: list[str] = []
        snapshot_ids: list[str] = []
        for record in sorted(records, key=lambda item: item.created_at, reverse=True):
            result = self.revert_snapshot(record.id, files=files)
            reverted_files.extend(result.reverted_files)
            if result.diff:
                diffs.append(result.diff)
            snapshot_ids.extend(result.snapshot_ids)
        return SnapshotRevertResult(
            scope="task",
            snapshot_ids=snapshot_ids,
            reverted_files=sorted(set(reverted_files)),
            diff="\n\n".join(item for item in diffs if item),
        )

    def list_snapshots(self, session_id: str) -> list[SnapshotRecord]:
        snapshots_dir = self._snapshots_dir(session_id)
        if not snapshots_dir.exists():
            return []
        records: list[SnapshotRecord] = []
        for path in sorted(snapshots_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            records.append(SnapshotRecord.from_dict(payload))
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def load(self, snapshot_id: str) -> SnapshotRecord:
        session_id, _sep, _rest = snapshot_id.partition(":")
        path = self._snapshot_path(session_id, snapshot_id)
        if not path.exists():
            raise FileNotFoundError(f"snapshot not found: {snapshot_id}")
        with self.store.lock(session_id):
            payload = json.loads(path.read_text(encoding="utf-8"))
        return SnapshotRecord.from_dict(payload)

    def _save(self, record: SnapshotRecord) -> None:
        path = self._snapshot_path(record.session_id, record.id)
        tmp_path = path.with_suffix(".json.tmp")
        payload = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
        with self.store.lock(record.session_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(path)

    def _latest_record(self, session_id: str, predicate) -> SnapshotRecord | None:
        for record in self.list_snapshots(session_id):
            if predicate(record):
                return record
        return None

    def _normalize_path(self, path: str) -> str:
        raw = Path(path)
        try:
            if raw.is_absolute():
                return raw.resolve().relative_to(self.workspace).as_posix()
        except ValueError:
            pass
        return str(raw).replace("\\", "/").lstrip("./")

    def _normalize_paths(self, paths: list[str]) -> list[str]:
        seen: list[str] = []
        for path in paths:
            normalized = self._normalize_path(path)
            if normalized and normalized not in seen:
                seen.append(normalized)
        return seen

    def _snapshots_dir(self, session_id: str) -> Path:
        return self.store.session_dir(session_id) / "snapshots"

    def _snapshot_path(self, session_id: str, snapshot_id: str) -> Path:
        return self._snapshots_dir(session_id) / f"{snapshot_id}.json"

    def _git_dir(self) -> Path:
        digest = hashlib.sha256(str(self.workspace).encode("utf-8")).hexdigest()[:16]
        return self._git_root / digest

    def _repo_lock(self) -> threading.RLock:
        key = str(self._git_dir())
        with self._repo_locks_guard:
            lock = self._repo_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._repo_locks[key] = lock
            return lock

    def _ensure_repo(self) -> None:
        git_dir = self._git_dir()
        if (git_dir / "HEAD").exists():
            return
        git_dir.mkdir(parents=True, exist_ok=True)
        self._git(["init"], extra_env={"GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(self.workspace)})
        self._git(["config", "core.autocrlf", "false"])
        self._git(["config", "core.longpaths", "true"])
        self._git(["config", "core.symlinks", "true"])
        self._git(["config", "core.fsmonitor", "false"])

    def _sync_excludes(self) -> None:
        exclude_path = self._git_dir() / "info" / "exclude"
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["/.openagent/", "/.git/", "/__pycache__/", "*.pyc"]
        for extra in (self.store.root_dir, self._git_root):
            try:
                rel = extra.resolve().relative_to(self.workspace)
            except ValueError:
                continue
            value = rel.as_posix().strip("/")
            if value:
                lines.append(f"/{value}/")
        text = "\n".join(lines) + "\n"
        exclude_path.write_text(text, encoding="utf-8")

    def _add_workspace(self) -> None:
        result = self._git(["add", "-A", "--", "."])
        if result.returncode != 0:
            raise RuntimeError(f"failed to add workspace to snapshot index: {result.stderr.strip()}")

    def _diff_against_hash(self, snapshot_hash: str, files: list[str] | None = None) -> str:
        args = ["diff", "--cached", "--no-ext-diff", snapshot_hash, "--", "."]
        if files:
            args = ["diff", "--cached", "--no-ext-diff", snapshot_hash, "--", *files]
        result = self._git(args, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"failed to get snapshot diff: {result.stderr.strip()}")
        return result.stdout.strip()

    def _revert_patch(self, patch: SnapshotPatch) -> None:
        with self._repo_lock():
            for file_path in patch.files:
                rel = self._normalize_path(file_path)
                checkout = self._git(["checkout", patch.snapshot_hash, "--", rel], check=False)
                if checkout.returncode == 0:
                    continue
                tree = self._git(["ls-tree", patch.snapshot_hash, "--", rel], check=False)
                absolute = (self.workspace / rel).resolve()
                if absolute.exists() and (self.workspace == absolute or self.workspace in absolute.parents):
                    if tree.returncode == 0 and tree.stdout.strip():
                        continue
                    if absolute.is_file():
                        absolute.unlink()
                    elif absolute.is_dir():
                        for child in sorted(absolute.rglob("*"), reverse=True):
                            if child.is_file():
                                child.unlink()
                            elif child.is_dir():
                                child.rmdir()
                        absolute.rmdir()

    def _git(
        self,
        args: list[str],
        *,
        check: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [
            "git",
            "--git-dir",
            str(self._git_dir()),
            "--work-tree",
            str(self.workspace),
            *args,
        ]
        env = None
        if extra_env:
            env = dict(os.environ)
            env.update(extra_env)
        result = subprocess.run(
            cmd,
            cwd=self.workspace,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"git command failed ({' '.join(args)}): {result.stderr.strip()}")
        return result

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event(type=event_type, payload=payload))


def build_snapshot_revert_message(result: SnapshotRevertResult) -> Message:
    parts = [
        Part(
            type="snapshot",
            content={
                "scope": result.scope,
                "snapshot_ids": result.snapshot_ids,
                "reverted_files": result.reverted_files,
            },
            state={"status": "reverted"},
        )
    ]
    if result.diff:
        parts.append(Part(type="patch", content=result.diff, state={"status": "completed"}))
    return Message(
        role="assistant",
        agent="session-op",
        content=f"[Snapshot Revert] reverted {len(result.reverted_files)} file(s).",
        finish="stop",
        parts=parts,
    )


def _snapshot_id(session_id: str, tool_call_id: str | None, tool_name: str, paths: list[str]) -> str:
    base = json.dumps(
        {"tool_call_id": tool_call_id, "tool_name": tool_name, "paths": paths, "time": utc_now_iso()},
        ensure_ascii=False,
    )
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]
    return f"{session_id}:{digest}"
