from __future__ import annotations

from abc import ABC, abstractmethod

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
