from __future__ import annotations

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
        if self.event_bus:
            self.event_bus.emit(Event(type="subagent.completed", payload={"summary_length": len(summary)}))
        return SubagentResult(summary=summary, history=history)
