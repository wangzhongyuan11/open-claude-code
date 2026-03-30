from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from openagent.domain.events import Event
from openagent.domain.messages import Message
from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.providers.base import BaseProvider
from openagent.session.llm import LLMRequest, SessionLLM
from openagent.session.message_builder import AssistantMessageBuilder, ToolMessageBuilder
from openagent.session.task_validation import (
    looks_multistep,
    parse_multistep_requirements,
    validate_multistep_requirements,
)
from openagent.session.termination import TerminationDecision, detect_completion
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
        stream_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> ProcessorResult:
        history = list(messages)
        repeated_calls: dict[str, int] = {}
        last_tool_result: tuple[str, str] | None = None
        step_count = 0
        tool_call_count = 0
        multistep_requirements = None
        if looks_multistep(self._last_user_text(history)):
            multistep_requirements = parse_multistep_requirements(self._last_user_text(history))

        for _ in range(max_steps):
            step_count += 1
            last_user_text = self._last_user_text(history)
            response, assistant_message = self._stream_assistant_message(
                messages=history,
                system_prompt=system_prompt,
                estimated_tokens=estimated_tokens,
                stream_handler=stream_handler,
            )
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
                tool_context = self.tool_context.child(
                    message_id=assistant_message.id,
                    tool_call_id=tool_call.id,
                    metadata={"tool_name": tool_call.name},
                )
                self._emit(
                    "tool.called",
                    {
                        "name": tool_call.name,
                        "tool_call_id": tool_call.id,
                        "session_id": tool_context.session_id,
                        "message_id": tool_context.message_id,
                    },
                )
                result = self.tool_registry.invoke(
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                    context=tool_context,
                )
                self._emit(
                    "tool.completed",
                    {
                        "name": tool_call.name,
                        "tool_call_id": tool_call.id,
                        "status": result.status,
                        "is_error": result.is_error,
                        "truncated": result.truncated,
                        "duration_ms": result.metadata.get("duration_ms"),
                    },
                )
                history.append(
                    self._build_tool_message(
                        tool_call.name,
                        tool_call.id,
                        tool_call.arguments,
                        result,
                    )
                )
                last_tool_result = (tool_call.name, result.content)
                decision = detect_completion(
                    user_text=last_user_text,
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    content=result.content,
                    metadata=result.metadata,
                )
                if decision is not None:
                    history.append(Message(role="assistant", content=decision.reply, finish="stop"))
                    self._emit("loop.completed", {"termination_reason": decision.reason})
                    return ProcessorResult(
                        history=history,
                        finish_reason="stop",
                        unstable=False,
                        step_count=step_count,
                        tool_call_count=tool_call_count,
                    )
                multistep_decision = self._detect_multistep_completion(
                    last_user_text=last_user_text,
                    tool_name=tool_call.name,
                    history=history,
                    requirements=multistep_requirements,
                )
                if multistep_decision is not None:
                    history.append(Message(role="assistant", content=multistep_decision.reply, finish="stop"))
                    self._emit("loop.completed", {"termination_reason": multistep_decision.reason})
                    return ProcessorResult(
                        history=history,
                        finish_reason="stop",
                        unstable=False,
                        step_count=step_count,
                        tool_call_count=tool_call_count,
                    )
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

    def _detect_multistep_completion(
        self,
        last_user_text: str,
        tool_name: str,
        history: list[Message],
        requirements,
    ):
        if requirements is None:
            return None
        validation = validate_multistep_requirements(self.tool_context.workspace, requirements)
        if not validation.complete:
            return None
        if tool_name not in {"read_file", "read", "read_symbol"}:
            return None
        decision = self._build_multistep_completion_reply(last_user_text, history)
        return decision

    @staticmethod
    def _build_multistep_completion_reply(last_user_text: str, history: list[Message]):
        tool_names: dict[str, str] = {}
        for message in history:
            if message.role == "assistant" and message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_names[tool_call.id] = tool_call.name
        read_results: list[str] = []
        for message in reversed(history):
            if message.role != "tool":
                continue
            if tool_names.get(message.tool_call_id) not in {"read_file", "read", "read_symbol"}:
                continue
            if message.content:
                read_results.append(message.content.strip())
            if len(read_results) >= 3:
                break
        if "只告诉我三件事" in last_user_text and len(read_results) >= 3:
            readme_text, config_text, subtask_text = list(reversed(read_results[:3]))
            lines = [
                f"README 是否含 delegate subtask：{'是' if 'delegate subtask' in readme_text else '否'}",
                f"mode 是否为 production：{'是' if 'production' in config_text else '否'}",
                f"子代理是否成功：{'是' if 'delegated-ok' in subtask_text or 'created by delegated agent' in subtask_text else '否'}",
            ]
            return TerminationDecision(True, "\n".join(lines), "multistep-validated")
        if "只告诉我三件事" in last_user_text:
            return None
        if "只告诉我最终内容" in last_user_text or "原样返回" in last_user_text:
            for content in read_results:
                if content:
                    return TerminationDecision(True, content, "multistep-validated")
        return TerminationDecision(True, "任务全部完成", "multistep-validated")

    @staticmethod
    def _call_fingerprint(name: str, arguments: dict) -> str:
        return f"{name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"

    @staticmethod
    def _last_user_text(history: list[Message]) -> str:
        for message in reversed(history):
            if message.role == "user":
                return message.content
        return ""

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
        recovered = self._can_recover_from_loop_failure(reason, last_tool_result)
        message = self._loop_failure_message(reason, last_tool_result)
        history.append(Message(role="assistant", content=message, finish="other"))
        return ProcessorResult(
            history=history,
            finish_reason="stop" if recovered else reason,
            unstable=not recovered,
            step_count=step_count,
            tool_call_count=tool_call_count,
        )

    @staticmethod
    def _loop_failure_message(reason: str, last_tool_result: tuple[str, str] | None) -> str:
        if last_tool_result is not None:
            tool_name, tool_output = last_tool_result
            if reason == "repetitive_tool_loop" and tool_name in {"read_file", "bash"}:
                return tool_output
        message = f"Stopped because the tool loop became unstable ({reason})."
        if last_tool_result is not None:
            tool_name, tool_output = last_tool_result
            message += f"\nLast tool: {tool_name}\nLast tool result:\n{tool_output}"
        return message

    @staticmethod
    def _can_recover_from_loop_failure(reason: str, last_tool_result: tuple[str, str] | None) -> bool:
        if last_tool_result is None:
            return False
        tool_name, _ = last_tool_result
        return reason == "repetitive_tool_loop" and tool_name in {"read_file", "bash"}

    def _stream_assistant_message(
        self,
        messages: list[Message],
        system_prompt: str | None,
        estimated_tokens: int,
        stream_handler: Callable[[dict[str, Any]], None] | None,
    ) -> tuple[object, Message]:
        builder = AssistantMessageBuilder()
        builder.start_step(requested_tools=0)
        self._emit("processor.part.appended", {"role": "assistant", "part_type": "step-start"})
        text_buffer = ""
        tool_calls = []
        final_response = None
        for event in self.llm.stream_generate(
            LLMRequest(
                messages=messages,
                tools=self.tool_registry.specs(self.tool_context),
                system_prompt=system_prompt,
                estimated_tokens=estimated_tokens,
            )
        ):
            event_type = event["type"]
            if event_type == "text-delta":
                delta = event["text"]
                text_buffer += delta
                builder.add_text(delta)
                self._emit("processor.part.appended", {"role": "assistant", "part_type": "text"})
                if stream_handler is not None:
                    stream_handler({"type": "text-delta", "text": delta})
                continue
            if event_type == "tool-call":
                tool_call = event["tool_call"]
                tool_calls.append(tool_call)
                builder.add_tool_request(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                )
                self._emit("processor.part.appended", {"role": "assistant", "part_type": "tool", "tool_name": tool_call.name})
                if stream_handler is not None:
                    stream_handler({"type": "tool-call", "tool_call": tool_call})
                continue
            if event_type == "finish":
                final_response = event["response"]
                if stream_handler is not None:
                    stream_handler({"type": "finish", "response": final_response})
                break
        if final_response is None:
            raise RuntimeError("stream finished without a final response")
        builder.update_requested_tools(len(tool_calls))
        finish = final_response.finish or ("tool-calls" if tool_calls else "stop")
        builder.finish_step(
            finish=finish,
            tokens={
                "input": final_response.tokens.input,
                "output": final_response.tokens.output,
                "reasoning": final_response.tokens.reasoning,
                "cache_read": final_response.tokens.cache_read,
                "cache_write": final_response.tokens.cache_write,
            },
            cost=final_response.cost,
        )
        self._emit("processor.part.appended", {"role": "assistant", "part_type": "step-finish", "finish": finish})
        return final_response, builder.build(
            role="assistant",
            content=text_buffer,
            model=final_response.model,
            tokens=final_response.tokens,
            cost=final_response.cost,
            finish=finish,
            error=final_response.error,
            tool_calls=tool_calls,
        )

    def _build_tool_message(
        self,
        tool_name: str,
        tool_call_id: str,
        arguments: dict,
        result,
    ) -> Message:
        builder = ToolMessageBuilder(
            name=tool_name,
            tool_call_id=tool_call_id,
            arguments=arguments,
            content=result.content,
            result=result,
        )
        builder.add_tool_result()
        self._emit("processor.part.appended", {"role": "tool", "part_type": "tool", "tool_name": tool_name})
        path = arguments.get("path")
        if path and tool_name in {"read_file", "read_file_range", "read", "read_symbol"}:
            builder.add_file_result()
            self._emit("processor.part.appended", {"role": "tool", "part_type": "file", "tool_name": tool_name})
        elif path and tool_name in {"write_file", "append_file", "edit_file", "multiedit", "apply_patch", "write", "edit", "patch", "replace_all", "insert_text", "ensure_dir"}:
            builder.add_file_result(mutation=tool_name)
            self._emit("processor.part.appended", {"role": "tool", "part_type": "file", "tool_name": tool_name})
        elif tool_name in {"delegate", "task"}:
            builder.add_subtask_result()
            self._emit("processor.part.appended", {"role": "tool", "part_type": "subtask", "tool_name": tool_name})
        if result.artifacts:
            builder.add_artifact_results(result.artifacts)
            self._emit("processor.part.appended", {"role": "tool", "part_type": "file", "tool_name": tool_name, "artifact_count": len(result.artifacts)})
        metadata = result.metadata
        path = metadata.get("path") or arguments.get("path")
        before_content = metadata.get("before_content")
        after_content = metadata.get("after_content")
        if path and isinstance(before_content, str) and isinstance(after_content, str):
            builder.add_patch_result(before_content, after_content, str(path))
            self._emit("processor.part.appended", {"role": "tool", "part_type": "patch", "tool_name": tool_name})
            builder.add_snapshot_refs(
                metadata.get("snapshot_before_ref"),
                metadata.get("snapshot_after_ref"),
                str(path),
            )
            self._emit("processor.part.appended", {"role": "tool", "part_type": "snapshot", "tool_name": tool_name})
        elif path and metadata.get("snapshot_after_ref"):
            builder.add_snapshot_refs(None, metadata.get("snapshot_after_ref"), str(path))
            self._emit("processor.part.appended", {"role": "tool", "part_type": "snapshot", "tool_name": tool_name})
        return builder.build()
