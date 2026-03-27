from __future__ import annotations

from dataclasses import dataclass

from openagent.domain.events import Event
from openagent.domain.messages import AgentResponse, Message
from openagent.domain.tools import ToolSpec
from openagent.events.bus import EventBus
from openagent.providers.base import BaseProvider


@dataclass(slots=True)
class LLMRequest:
    messages: list[Message]
    tools: list[ToolSpec]
    system_prompt: str | None = None
    estimated_tokens: int = 0


class SessionLLM:
    def __init__(self, provider: BaseProvider, event_bus: EventBus | None = None) -> None:
        self.provider = provider
        self.event_bus = event_bus

    def generate(self, request: LLMRequest) -> AgentResponse:
        self._emit(
            "model.requested",
            {
                "message_count": len(request.messages),
                "estimated_tokens": request.estimated_tokens,
                "tool_count": len(request.tools),
            },
        )
        response = self.provider.generate(
            messages=request.messages,
            tools=request.tools,
            system_prompt=request.system_prompt,
        )
        self._emit(
            "model.responded",
            {
                "text_length": len(response.text),
                "tool_call_count": len(response.tool_calls),
                "finish": response.finish,
            },
        )
        return response

    def _emit(self, event_type: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event(type=event_type, payload=payload))
