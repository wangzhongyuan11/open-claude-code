from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from openagent.agent.loop import AgentLoop
from openagent.domain.events import Event
from openagent.domain.messages import Message
from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.providers.base import BaseProvider
from openagent.tools.registry import ToolRegistry


ProviderFactory = Callable[[], BaseProvider]
RegistryFactory = Callable[[], ToolRegistry]


@dataclass(slots=True)
class SubagentResult:
    summary: str
    history: list[Message]
    touched_paths: list[str]
    verified_paths: list[str]


class SubagentManager:
    def __init__(
        self,
        provider_factory: ProviderFactory,
        registry_factory: RegistryFactory,
        workspace: Path,
        system_prompt: str,
        event_bus: EventBus | None = None,
    ) -> None:
        self.provider_factory = provider_factory
        self.registry_factory = registry_factory
        self.workspace = workspace.resolve()
        self.system_prompt = system_prompt
        self.event_bus = event_bus

    def run(self, prompt: str, max_steps: int = 8) -> SubagentResult:
        if self.event_bus:
            self.event_bus.emit(Event(type="subagent.started", payload={"prompt": prompt}))
        provider = self.provider_factory()
        registry = self.registry_factory()
        loop = AgentLoop(
            provider=provider,
            tool_registry=registry,
            tool_context=ToolContext(workspace=self.workspace, metadata={"agent": "subagent"}),
            event_bus=self.event_bus,
        )
        history = loop.run(
            messages=[Message(role="user", content=prompt)],
            system_prompt=self.system_prompt,
            max_steps=max_steps,
        )
        summary = next(
            (message.content for message in reversed(history) if message.role == "assistant" and message.content),
            "",
        )
        touched_paths, verified_paths = self._collect_artifacts(history)
        if self.event_bus:
            self.event_bus.emit(
                Event(
                    type="subagent.completed",
                    payload={
                        "summary_length": len(summary),
                        "touched_paths": touched_paths,
                        "verified_paths": verified_paths,
                    },
                )
            )
        return SubagentResult(
            summary=summary,
            history=history,
            touched_paths=touched_paths,
            verified_paths=verified_paths,
        )

    @staticmethod
    def _collect_artifacts(history: list[Message]) -> tuple[list[str], list[str]]:
        touched_paths: list[str] = []
        verified_paths: list[str] = []
        tool_call_paths: dict[str, tuple[str, str]] = {}
        for message in history:
            if message.role == "assistant" and message.tool_calls:
                for tool_call in message.tool_calls:
                    path = tool_call.arguments.get("path")
                    if not path:
                        continue
                    tool_call_paths[tool_call.id] = (tool_call.name, str(path))
                    if tool_call.name in {"write_file", "append_file", "edit_file"}:
                        touched_paths.append(str(path))
            elif message.role == "tool" and message.tool_call_id in tool_call_paths:
                tool_name, path = tool_call_paths[message.tool_call_id]
                if tool_name == "read_file":
                    verified_paths.append(path)
        return sorted(set(touched_paths)), sorted(set(verified_paths))


def format_subagent_report(result: SubagentResult) -> str:
    payload = {
        "status": "completed",
        "summary": result.summary,
        "touched_paths": result.touched_paths,
        "verified_paths": result.verified_paths,
    }
    return "<delegate_result>\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n</delegate_result>"
