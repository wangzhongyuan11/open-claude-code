from __future__ import annotations

import json

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
        repeated_calls: dict[str, int] = {}
        last_tool_result: tuple[str, str] | None = None
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
                last_tool_result = (tool_call.name, result.content)
                call_key = self._call_fingerprint(tool_call.name, tool_call.arguments)
                repeated_calls[call_key] = repeated_calls.get(call_key, 0) + 1
                if repeated_calls[call_key] >= 3:
                    return self._return_loop_failure(
                        history=history,
                        reason="repetitive_tool_loop",
                        details={
                            "tool_name": tool_call.name,
                            "tool_call_id": tool_call.id,
                            "repeat_count": repeated_calls[call_key],
                        },
                        last_tool_result=last_tool_result,
                    )
        return self._return_loop_failure(
            history=history,
            reason="max_steps_exceeded",
            details={"max_steps": max_steps},
            last_tool_result=last_tool_result,
        )

    def _emit(self, event_type: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event(type=event_type, payload=payload))

    @staticmethod
    def _call_fingerprint(name: str, arguments: dict) -> str:
        return f"{name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"

    def _return_loop_failure(
        self,
        history: list[Message],
        reason: str,
        details: dict,
        last_tool_result: tuple[str, str] | None,
    ) -> list[Message]:
        self._emit("loop.failed", {"reason": reason, **details})
        message = f"Stopped because the tool loop became unstable ({reason})."
        if last_tool_result is not None:
            tool_name, tool_output = last_tool_result
            message += f"\nLast tool: {tool_name}\nLast tool result:\n{tool_output}"
        history.append(Message(role="assistant", content=message))
        return history
