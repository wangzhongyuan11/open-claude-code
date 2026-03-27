from __future__ import annotations

from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.providers.base import BaseProvider
from openagent.session.processor import SessionProcessor
from openagent.tools.registry import ToolRegistry


class AgentLoop:
    def __init__(
        self,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
        tool_context: ToolContext,
        event_bus: EventBus | None = None,
    ) -> None:
        self.processor = SessionProcessor(
            provider=provider,
            tool_registry=tool_registry,
            tool_context=tool_context,
            event_bus=event_bus,
        )

    def run(
        self,
        messages,
        system_prompt: str | None = None,
        max_steps: int = 12,
        estimated_tokens: int = 0,
    ):
        return self.processor.process(
            messages=messages,
            system_prompt=system_prompt,
            max_steps=max_steps,
            estimated_tokens=estimated_tokens,
        ).history
