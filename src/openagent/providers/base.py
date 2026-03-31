from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from openagent.domain.messages import AgentResponse, Message
from openagent.domain.tools import ToolSpec


class BaseProvider(ABC):
    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        system_prompt: str | None = None,
    ) -> AgentResponse:
        raise NotImplementedError

    def stream_generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        system_prompt: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        response = self.generate(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
        )
        yield {"type": "start"}
        if response.text:
            yield {"type": "text-start"}
            yield {"type": "text-delta", "text": response.text}
            yield {"type": "text-end"}
        for tool_call in response.tool_calls:
            yield {"type": "tool-call", "tool_call": tool_call}
        yield {"type": "finish", "response": response}
