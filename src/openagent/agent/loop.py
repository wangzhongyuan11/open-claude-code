from __future__ import annotations

from openagent.domain.events import Event
from openagent.domain.messages import Message
from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.providers.base import BaseProvider
from openagent.tools.registry import ToolRegistry


class AgentLoop:
    def __init__(
        self,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
        tool_context: ToolContext,
        event_bus: EventBus | None = None,
    ) -> None:
        self.provider = provider
        self.tool_registry = tool_registry
        self.tool_context = tool_context
        self.event_bus = event_bus

    def run(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        max_steps: int = 12,
    ) -> list[Message]:
        history = list(messages)
        for _ in range(max_steps):
            self._emit("model.requested", {"message_count": len(history)})
            response = self.provider.generate(
                messages=history,
                tools=self.tool_registry.specs(),
                system_prompt=system_prompt,
            )
            self._emit(
                "model.responded",
                {
                    "text_length": len(response.text),
                    "tool_call_count": len(response.tool_calls),
                },
            )
            history.append(
                Message(
                    role="assistant",
                    content=response.text,
                    tool_calls=response.tool_calls,
                )
            )
            if not response.requests_tools:
                return history

            for tool_call in response.tool_calls:
                self._emit(
                    "tool.called",
                    {"name": tool_call.name, "tool_call_id": tool_call.id},
                )
                result = self.tool_registry.invoke(
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                    context=self.tool_context,
                )
                self._emit(
                    "tool.completed",
                    {
                        "name": tool_call.name,
                        "tool_call_id": tool_call.id,
                        "is_error": result.is_error,
                    },
                )
                history.append(
                    Message(
                        role="tool",
                        content=result.content,
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                )
        self._emit("loop.failed", {"reason": "max_steps_exceeded", "max_steps": max_steps})
        raise RuntimeError(f"agent loop exceeded max_steps={max_steps}")

    def _emit(self, event_type: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event(type=event_type, payload=payload))
