from __future__ import annotations

from pathlib import Path
import json
import time
from typing import Callable

from openagent.agent.loop import AgentLoop
from openagent.agent.subagent import SubagentManager
from openagent.config.settings import Settings
from openagent.domain.events import Event
from openagent.domain.messages import Message
from openagent.domain.session import Session
from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.events.logger import get_logger
from openagent.providers.base import BaseProvider
from openagent.providers.factory import build_provider
from openagent.session.manager import SessionManager
from openagent.session.store import SessionStore
from openagent.tools.builtin.bash import BashTool
from openagent.tools.builtin.delegate import DelegateTool
from openagent.tools.builtin.edit import EditFileTool
from openagent.tools.builtin.files import AppendFileTool, ListFilesTool, ReadFileTool, WriteFileTool
from openagent.tools.registry import ToolRegistry


DEFAULT_SYSTEM_PROMPT = """You are a Python coding agent working in a local repository.
Use tools when needed.
Prefer reading files before editing them.
Keep changes precise and minimal.
When a user asks for exact file contents or exact command output, return the actual tool result rather than a summary.
Avoid noisy listings of .git, .openagent, __pycache__, and test cache directories unless the user explicitly asks for them.
Treat delegate tool results as authoritative completion reports. If a delegate result already includes verified paths, do not re-read those files unless the user explicitly asks you to inspect the contents yourself."""

logger = get_logger(__name__)


class AgentRuntime:
    def __init__(
        self,
        provider: BaseProvider,
        workspace: Path,
        session_manager: SessionManager,
        session: Session,
        settings: Settings,
        event_bus: EventBus | None = None,
        provider_factory: Callable[[], BaseProvider] | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self.provider = provider
        self.workspace = workspace.resolve()
        self.session_manager = session_manager
        self.session = session
        self.settings = settings
        self.event_bus = event_bus
        self.provider_factory = provider_factory or (lambda: self.provider)
        self.system_prompt = system_prompt
        self.subagent_manager = self._build_subagent_manager()
        self.registry = self._build_registry()
        self.loop = AgentLoop(
            provider=self.provider,
            tool_registry=self.registry,
            tool_context=ToolContext(workspace=self.workspace),
            event_bus=self.event_bus,
        )

    def run_turn(self, user_text: str) -> str:
        self._emit("message.added", {"role": "user", "session_id": self.session.id})
        self.session_manager.append_message(
            self.session,
            Message(role="user", content=user_text),
            mark_running_state=True,
        )
        prompt_context = self.session_manager.build_prompt(self.session, self.system_prompt)
        try:
            history = self.loop.run(
                messages=prompt_context.messages,
                system_prompt=prompt_context.system_prompt,
                estimated_tokens=prompt_context.estimated_tokens,
            )
            new_messages = history[len(prompt_context.messages):]
            self.session_manager.append_turn_messages(self.session, new_messages)
            last_assistant = next(
                (message.content for message in reversed(self.session.messages) if message.role == "assistant"),
                "",
            )
            self._emit("loop.completed", {"session_id": self.session.id, "assistant_length": len(last_assistant)})
            logger.info("Completed turn for session %s", self.session.id)
            return last_assistant
        except Exception as exc:
            self.session_manager.fail_turn(self.session, str(exc))
            self._emit("loop.failed", {"session_id": self.session.id, "error": str(exc)})
            raise

    @property
    def session_id(self) -> str:
        return self.session.id

    def status_report(self) -> str:
        payload = {
            "session_id": self.session.id,
            "state": self.session.status.state,
            "retry_count": self.session.status.retry_count,
            "last_error": self.session.status.last_error,
            "recovery_hint": self.session.status.recovery_hint,
            "summary_present": self.session.summary is not None,
            "compacted_message_count": self.session.summary.compacted_message_count if self.session.summary else 0,
            "message_count": len(self.session.messages),
            "todo_count": len(self.session.todos),
            "prompt_token_estimate": self.session.metadata.get("prompt_token_estimate"),
            "compacted_token_estimate": self.session.metadata.get("compacted_token_estimate"),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def compact_session(self) -> str:
        changed = self.session_manager.compact(self.session)
        if not changed:
            return "Compaction not needed."
        return (
            f"Compacted session. Summary now covers "
            f"{self.session.summary.compacted_message_count if self.session.summary else 0} messages."
        )

    def revert_last_turn(self) -> str:
        changed = self.session_manager.revert_last_turn(self.session)
        return "Reverted last turn." if changed else "No turn to revert."

    def retry_last_turn(self) -> str:
        last_user_message = self.session_manager.retry_last_turn(self.session)
        if not last_user_message:
            return "No previous user message to retry."
        self.session_manager.revert_last_turn(self.session)
        time.sleep(self.session_manager.retry_delay_ms(self.session) / 1000)
        return self.run_turn(last_user_message)

    def add_todo(self, content: str, priority: str = "medium") -> str:
        self.session_manager.add_todo(self.session, content, priority)
        return f"Added todo: {content}"

    def complete_todo(self, index: int) -> str:
        self.session_manager.complete_todo(self.session, index)
        return f"Completed todo #{index + 1}"

    def clear_todos(self) -> str:
        self.session_manager.clear_todos(self.session)
        return "Cleared todos."

    def _build_subagent_manager(self) -> SubagentManager:
        return SubagentManager(
            provider_factory=self.provider_factory,
            registry_factory=self._build_subagent_registry,
            workspace=self.workspace,
            system_prompt="You are a focused coding subagent. Investigate or make a small targeted change, then summarize clearly.",
            event_bus=self.event_bus,
        )

    def _build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(AppendFileTool())
        registry.register(EditFileTool())
        registry.register(ListFilesTool())
        registry.register(BashTool(timeout_seconds=self.settings.bash_timeout_seconds))
        registry.register(DelegateTool(self.subagent_manager))
        return registry

    def _build_subagent_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(AppendFileTool())
        registry.register(EditFileTool())
        registry.register(ListFilesTool())
        registry.register(BashTool(timeout_seconds=self.settings.bash_timeout_seconds))
        return registry

    def _emit(self, event_type: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event(type=event_type, payload=payload))


def build_default_runtime(
    workspace: str | Path = ".",
    session_id: str | None = None,
    session_root: str | Path | None = None,
) -> AgentRuntime:
    settings = Settings.from_workspace(workspace)
    workspace_path = settings.workspace
    manager = build_session_manager(workspace=workspace_path, session_root=session_root or settings.session_root)
    session = manager.start(workspace=workspace_path, session_id=session_id)
    event_bus = EventBus(settings.log_root / f"{session.id}.jsonl")
    def provider_factory() -> BaseProvider:
        return build_provider(settings)

    provider = provider_factory()
    return AgentRuntime(
        provider=provider,
        workspace=workspace_path,
        session_manager=manager,
        session=session,
        settings=settings,
        event_bus=event_bus,
        provider_factory=provider_factory,
    )


def build_session_manager(
    workspace: str | Path = ".",
    session_root: str | Path | None = None,
) -> SessionManager:
    settings = Settings.from_workspace(workspace)
    store = SessionStore(Path(session_root) if session_root else settings.session_root)
    return SessionManager(
        store,
        max_messages_before_compact=settings.compact_max_messages,
        prompt_recent_messages=settings.prompt_recent_messages,
        prompt_max_tokens=settings.prompt_max_tokens,
    )
