from __future__ import annotations

import os

from openagent.domain.messages import AgentResponse, Message, ToolCall
from openagent.domain.tools import ToolSpec
from openagent.providers.base import BaseProvider


class AnthropicProvider(BaseProvider):
    def __init__(self, model: str, max_tokens: int = 4096):
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic SDK is not installed. Run: pip install -e '.[anthropic]'"
            ) from exc
        self._client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self._model = model
        self._max_tokens = max_tokens

    def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        system_prompt: str | None = None,
    ) -> AgentResponse:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_prompt or "",
            messages=[self._to_anthropic_message(message) for message in messages],
            tools=[self._to_anthropic_tool(tool) for tool in tools],
        )
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input),
                    )
                )
        return AgentResponse(text="".join(text_parts), tool_calls=tool_calls, raw=response)

    @staticmethod
    def _to_anthropic_tool(tool: ToolSpec) -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }

    @staticmethod
    def _to_anthropic_message(message: Message) -> dict:
        if message.role == "tool":
            if not message.tool_call_id:
                raise ValueError("tool message requires tool_call_id")
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": message.content,
                        "is_error": False,
                    }
                ],
            }
        if message.role == "assistant" and message.tool_calls:
            content: list[dict] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            for tool_call in message.tool_calls:
                content.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "input": tool_call.arguments,
                    }
                )
            return {
                "role": "assistant",
                "content": content,
            }
        return {
            "role": message.role,
            "content": message.content,
        }
