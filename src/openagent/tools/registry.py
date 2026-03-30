from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from typing import Callable

from openagent.domain.events import Event
from openagent.domain.tools import ToolContext, ToolExecutionResult, ToolSpec
from openagent.extensions.base import ExtensionContext, PermissionPolicy
from openagent.extensions.defaults import AllowAllPolicy
from openagent.permission.models import PermissionReply, PermissionRequest
from openagent.tools.base import BaseTool
from openagent.tools.truncation import apply_output_truncation

ToolFactory = Callable[[], BaseTool]
ToolVisibility = Callable[[ToolContext | None], bool]


@dataclass(slots=True)
class ToolRegistration:
    tool_id: str
    factory: ToolFactory
    source: str
    visible: ToolVisibility | None = None


class ToolRegistry:
    def __init__(self, permission_policy: PermissionPolicy | None = None) -> None:
        self._registrations: dict[str, ToolRegistration] = {}
        self._permission_policy = permission_policy or AllowAllPolicy()

    def register(self, tool: BaseTool, *, source: str | None = None, visible: ToolVisibility | None = None) -> None:
        self.register_factory(tool.id, lambda tool=tool: tool, source=source or tool.source, visible=visible)

    def register_factory(
        self,
        tool_id: str,
        factory: ToolFactory,
        *,
        source: str = "custom",
        visible: ToolVisibility | None = None,
    ) -> None:
        if tool_id in self._registrations:
            raise ValueError(f"tool already registered: {tool_id}")
        self._registrations[tool_id] = ToolRegistration(tool_id=tool_id, factory=factory, source=source, visible=visible)

    def get(self, tool_id: str) -> BaseTool:
        try:
            registration = self._registrations[tool_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {tool_id}") from exc
        return registration.factory()

    def ids(self, context: ToolContext | None = None) -> list[str]:
        return [registration.tool_id for registration in self._available_registrations(context)]

    def tools(self, context: ToolContext | None = None) -> list[BaseTool]:
        return [registration.factory() for registration in self._available_registrations(context)]

    def specs(self, context: ToolContext | None = None) -> list[ToolSpec]:
        return [tool.spec() for tool in self.tools(context)]

    def invoke(self, name: str, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        started = time.perf_counter()
        self._emit(
            context,
            "tool.pending",
            {"tool_id": name, "tool_call_id": context.tool_call_id, "session_id": context.session_id},
        )
        decision = self._permission_policy.check(
            ExtensionContext(
                tool_name=name,
                arguments=arguments,
                tool_context=context,
            )
        )
        if decision.action == "ask" and decision.request is not None:
            approval = self._resolve_permission_approval(context, decision.request)
            if approval == "reject":
                result = ToolExecutionResult.failure(
                    "permission rejected by user",
                    error_type="permission_rejected",
                    hint="Try a narrower request or ask the user to approve the action.",
                    metadata={"tool": name},
                )
                self._emit_result(context, name, result, started)
                return result
        elif not decision.allowed:
            result = ToolExecutionResult.failure(
                decision.reason or "permission denied",
                error_type="permission_denied",
                hint=decision.reason,
                metadata={"tool": name},
            )
            self._emit_result(context, name, result, started)
            return result

        try:
            tool = self.get(name)
            tool.init(context)
            tool.validate_arguments(arguments)
            self._emit(
                context,
                "tool.running",
                {"tool_id": tool.id, "tool_call_id": context.tool_call_id, "session_id": context.session_id},
            )
            result = tool.invoke(arguments, context)
            if not result.title:
                result.title = tool.name
            result.metadata = {
                **result.metadata,
                "tool_id": tool.id,
                "tool_name": tool.name,
                "tool_source": tool.source,
                "session_id": context.session_id,
                "message_id": context.message_id,
                "tool_call_id": context.tool_call_id,
            }
            result = apply_output_truncation(
                result,
                tool_id=tool.id,
                workspace=context.workspace,
                limits=tool.get_output_limits(),
            )
        except KeyError as exc:
            result = ToolExecutionResult.failure(
                str(exc),
                error_type="unknown_tool",
                retryable=False,
                hint="Choose one of the currently visible tools for this agent mode.",
                metadata={"tool": name},
            )
        except Exception as exc:
            tb = traceback.format_exc()
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            result = ToolExecutionResult.failure(
                f"tool '{name}' failed: {detail}",
                error_type=type(exc).__name__,
                retryable=False,
                hint="Inspect the tool arguments and workspace state, then retry with a narrower request.",
                metadata={"tool": name},
                traceback=tb,
            )
        self._emit_result(context, name, result, started)
        return result

    def _resolve_permission_approval(self, context: ToolContext, request: PermissionRequest) -> PermissionReply:
        if hasattr(self._permission_policy, "record_request"):
            self._permission_policy.record_request(request)
        yolo = str(context.runtime_state.get("yolo_mode", "false")).lower() == "true"
        if yolo:
            if hasattr(self._permission_policy, "record_reply"):
                self._permission_policy.record_reply(request, "once", yolo=True)
            self._emit(
                context,
                "permission.auto_approved",
                {
                    "session_id": request.session_id,
                    "request_id": request.id,
                    "tool_name": request.tool_name,
                    "pattern": request.pattern,
                },
            )
            return "once"
        asker = context.runtime_state.get("ask_permission")
        if not callable(asker):
            if hasattr(self._permission_policy, "record_reply"):
                self._permission_policy.record_reply(request, "reject", yolo=False)
            return "reject"
        reply = asker(request)
        if reply not in {"once", "always", "reject"}:
            reply = "reject"
        if hasattr(self._permission_policy, "record_reply"):
            self._permission_policy.record_reply(request, reply, yolo=False)
        return reply

    def _available_registrations(self, context: ToolContext | None) -> list[ToolRegistration]:
        available: list[ToolRegistration] = []
        for registration in self._registrations.values():
            if registration.visible is not None and not registration.visible(context):
                continue
            available.append(registration)
        return available

    @staticmethod
    def _emit(context: ToolContext, event_type: str, payload: dict) -> None:
        if context.event_bus is None:
            return
        context.event_bus.emit(Event(type=event_type, payload=payload))

    def _emit_result(
        self,
        context: ToolContext,
        tool_id: str,
        result: ToolExecutionResult,
        started: float,
    ) -> None:
        duration_ms = int((time.perf_counter() - started) * 1000)
        result.metadata["duration_ms"] = str(duration_ms)
        result.metadata["status"] = result.status
        if result.truncated:
            result.metadata["truncated"] = "true"
        event_type = {
            "succeeded": "tool.succeeded",
            "failed": "tool.failed",
            "timed_out": "tool.timed_out",
            "cancelled": "tool.cancelled",
        }.get(result.status, "tool.completed")
        self._emit(
            context,
            event_type,
            {
                "tool_id": tool_id,
                "tool_call_id": context.tool_call_id,
                "session_id": context.session_id,
                "status": result.status,
                "duration_ms": duration_ms,
                "truncated": result.truncated,
                "has_error": result.is_error,
            },
        )
