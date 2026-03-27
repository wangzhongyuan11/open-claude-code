from __future__ import annotations

import json
from dataclasses import dataclass

from openagent.domain.events import Event
from openagent.domain.messages import Message, Part
from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.providers.base import BaseProvider
from openagent.session.llm import LLMRequest, SessionLLM
from openagent.tools.registry import ToolRegistry


@dataclass(slots=True)
class ProcessorResult:
    history: list[Message]
    finish_reason: str
    unstable: bool = False


class SessionProcessor:
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
        self.llm = SessionLLM(provider=provider, event_bus=event_bus)

    def process(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        max_steps: int = 12,
        estimated_tokens: int = 0,
    ) -> ProcessorResult:
        history = list(messages)
        repeated_calls: dict[str, int] = {}
        last_tool_result: tuple[str, str] | None = None

        for _ in range(max_steps):
            response = self.llm.generate(
                LLMRequest(
                    messages=history,
                    tools=self.tool_registry.specs(),
                    system_prompt=system_prompt,
                    estimated_tokens=estimated_tokens,
                )
            )
            assistant_message = self._build_assistant_message(response)
            history.append(assistant_message)
            if not response.requests_tools:
                return ProcessorResult(history=history, finish_reason=response.finish or "stop")

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
                history.append(self._build_tool_message(tool_call.name, tool_call.id, tool_call.arguments, result.content, result.is_error))
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
    ) -> ProcessorResult:
        self._emit("loop.failed", {"reason": reason, **details})
        message = f"Stopped because the tool loop became unstable ({reason})."
        if last_tool_result is not None:
            tool_name, tool_output = last_tool_result
            message += f"\nLast tool: {tool_name}\nLast tool result:\n{tool_output}"
        history.append(Message(role="assistant", content=message, finish="other"))
        return ProcessorResult(history=history, finish_reason=reason, unstable=True)

    @staticmethod
    def _build_assistant_message(response) -> Message:
        finish = response.finish or ("tool-calls" if response.tool_calls else "stop")
        parts: list[Part] = [
            Part(
                type="step-start",
                content={"phase": "llm", "requested_tools": len(response.tool_calls)},
                state={"status": "started"},
            )
        ]
        if response.text:
            parts.append(Part(type="text", content=response.text))
        for tool_call in response.tool_calls:
            parts.append(
                Part(
                    type="tool",
                    content={
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    },
                    state={"status": "requested"},
                )
            )
        parts.append(
            Part(
                type="step-finish",
                content={
                    "finish": finish,
                    "tokens": {
                        "input": response.tokens.input,
                        "output": response.tokens.output,
                        "reasoning": response.tokens.reasoning,
                        "cache_read": response.tokens.cache_read,
                        "cache_write": response.tokens.cache_write,
                    },
                    "cost": response.cost,
                },
                state={"status": "completed"},
            )
        )
        return Message(
            role="assistant",
            content=response.text,
            model=response.model,
            tokens=response.tokens,
            cost=response.cost,
            finish=finish,
            error=response.error,
            tool_calls=response.tool_calls,
            parts=parts,
        )

    @staticmethod
    def _build_tool_message(
        tool_name: str,
        tool_call_id: str,
        arguments: dict,
        content: str,
        is_error: bool,
    ) -> Message:
        status = "error" if is_error else "completed"
        parts: list[Part] = [
            Part(
                type="tool",
                content={
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "arguments": arguments,
                    "output": content,
                },
                state={"status": status},
            )
        ]
        path = arguments.get("path")
        if path and tool_name == "read_file":
            parts.append(
                Part(
                    type="file",
                    content={
                        "source": "file",
                        "path": str(path),
                        "content": content,
                    },
                    state={"status": status},
                )
            )
        return Message(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            parts=parts,
        )
