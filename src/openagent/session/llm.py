from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from uuid import uuid4

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

    def stream_generate(self, request: LLMRequest) -> Iterable[dict[str, Any]]:
        self._emit(
            "model.requested",
            {
                "message_count": len(request.messages),
                "estimated_tokens": request.estimated_tokens,
                "tool_count": len(request.tools),
                "mode": "stream",
            },
        )
        text_started = False
        reasoning_started = False
        text_id = uuid4().hex[:8]
        reasoning_id = uuid4().hex[:8]

        for event in self.provider.stream_generate(
            messages=request.messages,
            tools=request.tools,
            system_prompt=request.system_prompt,
        ):
            for normalized in self._normalize_stream_event(
                event,
                text_started=text_started,
                reasoning_started=reasoning_started,
                text_id=text_id,
                reasoning_id=reasoning_id,
            ):
                event_type = normalized.get("type", "unknown")
                if event_type == "text-start":
                    text_started = True
                elif event_type == "text-end":
                    text_started = False
                elif event_type == "reasoning-start":
                    reasoning_started = True
                elif event_type == "reasoning-end":
                    reasoning_started = False
                payload = {"type": event_type}
                if "id" in normalized:
                    payload["id"] = normalized["id"]
                if "text" in normalized:
                    payload["text_length"] = len(normalized["text"])
                self._emit("model.stream.event", payload)
                if event_type == "finish":
                    response = normalized["response"]
                    self._emit(
                        "model.responded",
                        {
                            "text_length": len(response.text),
                            "tool_call_count": len(response.tool_calls),
                            "finish": response.finish,
                            "mode": "stream",
                        },
                    )
                yield normalized

    @staticmethod
    def _normalize_stream_event(
        event: dict[str, Any],
        *,
        text_started: bool,
        reasoning_started: bool,
        text_id: str,
        reasoning_id: str,
    ) -> list[dict[str, Any]]:
        event_type = event.get("type", "unknown")
        if event_type == "text-delta":
            normalized: list[dict[str, Any]] = []
            if reasoning_started:
                normalized.append({"type": "reasoning-end", "id": reasoning_id})
            if not text_started:
                normalized.append({"type": "text-start", "id": text_id})
            normalized.append({"type": "text-delta", "id": text_id, "text": event.get("text", "")})
            return normalized
        if event_type == "reasoning-delta":
            normalized = []
            if not reasoning_started:
                normalized.append({"type": "reasoning-start", "id": reasoning_id})
            normalized.append({"type": "reasoning-delta", "id": reasoning_id, "text": event.get("text", "")})
            return normalized
        if event_type == "text-start":
            return [{"type": "text-start", "id": event.get("id", text_id)}]
        if event_type == "text-end":
            return [{"type": "text-end", "id": event.get("id", text_id)}]
        if event_type == "reasoning-start":
            return [{"type": "reasoning-start", "id": event.get("id", reasoning_id)}]
        if event_type == "reasoning-end":
            return [{"type": "reasoning-end", "id": event.get("id", reasoning_id)}]
        if event_type == "finish":
            normalized: list[dict[str, Any]] = []
            if reasoning_started:
                normalized.append({"type": "reasoning-end", "id": reasoning_id})
            if text_started:
                normalized.append({"type": "text-end", "id": text_id})
            normalized.append(event)
            return normalized
        return [event]

    def _emit(self, event_type: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event(type=event_type, payload=payload))
