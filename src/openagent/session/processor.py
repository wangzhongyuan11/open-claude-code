from __future__ import annotations

import json
from dataclasses import dataclass

from openagent.domain.events import Event
from openagent.domain.messages import Message
from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.providers.base import BaseProvider
from openagent.session.llm import LLMRequest, SessionLLM
from openagent.session.message_builder import AssistantMessageBuilder, ToolMessageBuilder
from openagent.tools.registry import ToolRegistry


@dataclass(slots=True)
class ProcessorResult:
    history: list[Message]
    finish_reason: str
    unstable: bool = False
    step_count: int = 0
    tool_call_count: int = 0


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
        step_count = 0
        tool_call_count = 0

        for _ in range(max_steps):
            step_count += 1
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
                return ProcessorResult(
                    history=history,
                    finish_reason=response.finish or "stop",
                    step_count=step_count,
                    tool_call_count=tool_call_count,
                )

            for tool_call in response.tool_calls:
                tool_call_count += 1
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
                        step_count=step_count,
                        tool_call_count=tool_call_count,
                    )

        return self._return_loop_failure(
            history=history,
            reason="max_steps_exceeded",
            details={"max_steps": max_steps},
            last_tool_result=last_tool_result,
            step_count=step_count,
            tool_call_count=tool_call_count,
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
        step_count: int,
        tool_call_count: int,
    ) -> ProcessorResult:
        self._emit("loop.failed", {"reason": reason, **details})
        message = f"Stopped because the tool loop became unstable ({reason})."
        if last_tool_result is not None:
            tool_name, tool_output = last_tool_result
            message += f"\nLast tool: {tool_name}\nLast tool result:\n{tool_output}"
        history.append(Message(role="assistant", content=message, finish="other"))
        return ProcessorResult(
            history=history,
            finish_reason=reason,
            unstable=True,
            step_count=step_count,
            tool_call_count=tool_call_count,
        )

    def _build_assistant_message(self, response) -> Message:
        finish = response.finish or ("tool-calls" if response.tool_calls else "stop")
        builder = AssistantMessageBuilder()
        builder.start_step(requested_tools=len(response.tool_calls))
        self._emit("processor.part.appended", {"role": "assistant", "part_type": "step-start"})
        if response.text:
            builder.add_text(response.text)
            self._emit("processor.part.appended", {"role": "assistant", "part_type": "text"})
        for tool_call in response.tool_calls:
            builder.add_tool_request(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=tool_call.arguments,
            )
            self._emit("processor.part.appended", {"role": "assistant", "part_type": "tool", "tool_name": tool_call.name})
        builder.finish_step(
            finish=finish,
            tokens={
                "input": response.tokens.input,
                "output": response.tokens.output,
                "reasoning": response.tokens.reasoning,
                "cache_read": response.tokens.cache_read,
                "cache_write": response.tokens.cache_write,
            },
            cost=response.cost,
        )
        self._emit("processor.part.appended", {"role": "assistant", "part_type": "step-finish", "finish": finish})
        return builder.build(
            role="assistant",
            content=response.text,
            model=response.model,
            tokens=response.tokens,
            cost=response.cost,
            finish=finish,
            error=response.error,
            tool_calls=response.tool_calls,
        )

    def _build_tool_message(self, tool_name: str, tool_call_id: str, arguments: dict, content: str, is_error: bool) -> Message:
        builder = ToolMessageBuilder(
            name=tool_name,
            tool_call_id=tool_call_id,
            arguments=arguments,
            content=content,
            is_error=is_error,
        )
        builder.add_tool_result()
        self._emit("processor.part.appended", {"role": "tool", "part_type": "tool", "tool_name": tool_name})
        path = arguments.get("path")
        if path and tool_name == "read_file":
            builder.add_file_result()
            self._emit("processor.part.appended", {"role": "tool", "part_type": "file", "tool_name": tool_name})
        elif path and tool_name in {"write_file", "append_file", "edit_file"}:
            builder.add_file_result(mutation=tool_name)
            self._emit("processor.part.appended", {"role": "tool", "part_type": "file", "tool_name": tool_name})
        elif tool_name == "delegate":
            builder.add_subtask_result()
            self._emit("processor.part.appended", {"role": "tool", "part_type": "subtask", "tool_name": tool_name})
        return builder.build()
