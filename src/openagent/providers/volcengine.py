from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

from openagent.domain.messages import AgentResponse, Message, ModelRef, TokenUsage, ToolCall
from openagent.domain.tools import ToolSpec
from openagent.providers.base import BaseProvider


class VolcengineProvider(BaseProvider):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("ARK_API_KEY") or os.getenv("VOLCENGINE_ARK_API_KEY")
        self.base_url = (
            (base_url or os.getenv("ARK_BASE_URL") or os.getenv("OPENAGENT_BASE_URL"))
            or "https://operator.las.cn-beijing.volces.com/api/v1"
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise RuntimeError("Volcengine provider requires ARK_API_KEY or VOLCENGINE_ARK_API_KEY")
        if not self.model:
            raise RuntimeError("Volcengine provider requires a model or endpoint id")

    def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        system_prompt: str | None = None,
    ) -> AgentResponse:
        payload = {
            "model": self.model,
            "messages": self._to_chat_messages(messages, system_prompt),
            "tools": [self._to_openai_tool(tool) for tool in tools],
        }
        raw_response = self._post_json("/chat/completions", payload)
        return self._parse_response(raw_response)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Volcengine API HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Volcengine API connection failed: {exc.reason}") from exc

    @staticmethod
    def _to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @staticmethod
    def _to_chat_messages(messages: list[Message], system_prompt: str | None) -> list[dict[str, Any]]:
        chat_messages: list[dict[str, Any]] = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})

        for message in messages:
            if message.role == "tool":
                chat_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
                continue

            if message.role == "assistant" and message.tool_calls:
                assistant_message: dict[str, Any] = {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.name,
                                "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                            },
                        }
                        for tool_call in message.tool_calls
                    ],
                }
                chat_messages.append(assistant_message)
                continue

            chat_messages.append({"role": message.role, "content": message.content})
        return chat_messages

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> AgentResponse:
        choices = payload.get("choices", [])
        if not choices:
            raise RuntimeError(f"Volcengine API returned no choices: {payload}")
        choice = choices[0]
        message = choice.get("message", {})
        tool_calls = []
        for item in message.get("tool_calls", []) or []:
            function = item.get("function", {})
            arguments = function.get("arguments") or "{}"
            tool_calls.append(
                ToolCall(
                    id=item["id"],
                    name=function["name"],
                    arguments=json.loads(arguments),
                )
            )
        usage = payload.get("usage", {})
        finish_reason = choice.get("finish_reason")
        finish = "tool-calls" if tool_calls else _map_openai_finish_reason(finish_reason)
        return AgentResponse(
            text=message.get("content") or "",
            tool_calls=tool_calls,
            finish=finish,
            model=ModelRef(provider_id="volcengine", model_id=payload.get("model", "unknown")),
            tokens=TokenUsage(
                input=usage.get("prompt_tokens", 0),
                output=usage.get("completion_tokens", 0),
                reasoning=usage.get("reasoning_tokens", 0),
                cache_read=usage.get("prompt_cache_hit_tokens", 0),
                cache_write=usage.get("prompt_cache_miss_tokens", 0),
            ),
            raw=payload,
        )


def _map_openai_finish_reason(value: str | None) -> str:
    mapping = {
        "stop": "stop",
        "length": "length",
        "content_filter": "content-filter",
        "tool_calls": "tool-calls",
    }
    return mapping.get(value or "", "other")
