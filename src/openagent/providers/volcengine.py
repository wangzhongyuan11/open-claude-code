from __future__ import annotations

import json
import os
from typing import Any, Iterable
from urllib import error, request

from openagent.domain.messages import AgentResponse, Message, MessageError, ModelRef, TokenUsage, ToolCall
from openagent.domain.tools import ToolSpec
from openagent.providers.base import BaseProvider


class VolcengineProvider(BaseProvider):
    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 60,
        max_tokens: int | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("ARK_API_KEY") or os.getenv("VOLCENGINE_ARK_API_KEY")
        self.base_url = (
            (base_url or os.getenv("ARK_BASE_URL") or os.getenv("OPENAGENT_BASE_URL"))
            or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens or int(os.getenv("OPENAGENT_MAX_TOKENS", "8192"))
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
            "max_tokens": self.max_tokens,
        }
        raw_response = self._post_json("/chat/completions", payload)
        return self._parse_response(raw_response)

    def stream_generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        system_prompt: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        payload = {
            "model": self.model,
            "messages": self._to_chat_messages(messages, system_prompt),
            "tools": [self._to_openai_tool(tool) for tool in tools],
            "stream": True,
            "max_tokens": self.max_tokens,
        }
        yield {"type": "start"}
        text_parts: list[str] = []
        tool_call_buffers: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage_payload: dict[str, Any] = {}
        model_name = self.model

        for chunk in self._post_stream_json("/chat/completions", payload):
            model_name = chunk.get("model", model_name)
            usage_payload = chunk.get("usage") or usage_payload
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                reasoning = self._extract_reasoning_delta(delta)
                if reasoning:
                    yield {"type": "reasoning-delta", "text": reasoning}
                content = delta.get("content")
                if content:
                    text_parts.append(content)
                    yield {"type": "text-delta", "text": content}
                for item in delta.get("tool_calls", []) or []:
                    index = item.get("index", 0)
                    entry = tool_call_buffers.setdefault(
                        index,
                        {
                            "id": None,
                            "name": None,
                            "arguments_parts": [],
                        },
                    )
                    if item.get("id"):
                        entry["id"] = item["id"]
                    function = item.get("function", {})
                    if function.get("name"):
                        entry["name"] = function["name"]
                    if function.get("arguments"):
                        entry["arguments_parts"].append(function["arguments"])
                finish_reason = choice.get("finish_reason") or finish_reason

        tool_calls: list[ToolCall] = []
        for index in sorted(tool_call_buffers):
            item = tool_call_buffers[index]
            arguments = "".join(item["arguments_parts"]) or "{}"
            parsed_arguments, parse_error = _parse_tool_arguments(arguments)
            if parse_error is not None:
                error_message = f"Malformed tool call arguments for {item['name'] or 'unknown_tool'}: {parse_error}"
                yield {
                    "type": "finish",
                    "response": AgentResponse(
                        text=("".join(text_parts) or error_message),
                        tool_calls=[],
                        finish="other",
                        model=ModelRef(provider_id="volcengine", model_id=model_name),
                        tokens=TokenUsage(
                            input=usage_payload.get("prompt_tokens", 0),
                            output=usage_payload.get("completion_tokens", 0),
                            reasoning=usage_payload.get("reasoning_tokens", 0),
                            cache_read=usage_payload.get("prompt_cache_hit_tokens", 0),
                            cache_write=usage_payload.get("prompt_cache_miss_tokens", 0),
                        ),
                        error=MessageError(
                            code="malformed_tool_arguments",
                            message=error_message,
                            details={
                                "tool_name": item["name"] or "unknown_tool",
                                "arguments_preview": arguments[:500],
                            },
                        ),
                        raw={"tool_call_index": index, "arguments": arguments},
                    ),
                }
                return
            tool_call = ToolCall(
                id=item["id"] or f"tool-call-{index}",
                name=item["name"] or "unknown_tool",
                arguments=parsed_arguments,
            )
            tool_calls.append(tool_call)
            yield {"type": "tool-call", "tool_call": tool_call}

        finish = "tool-calls" if tool_calls else _map_openai_finish_reason(finish_reason)
        yield {
            "type": "finish",
            "response": AgentResponse(
                text="".join(text_parts),
                tool_calls=tool_calls,
                finish=finish,
                model=ModelRef(provider_id="volcengine", model_id=model_name),
                tokens=TokenUsage(
                    input=usage_payload.get("prompt_tokens", 0),
                    output=usage_payload.get("completion_tokens", 0),
                    reasoning=usage_payload.get("reasoning_tokens", 0),
                    cache_read=usage_payload.get("prompt_cache_hit_tokens", 0),
                    cache_write=usage_payload.get("prompt_cache_miss_tokens", 0),
                ),
            ),
        }

    @staticmethod
    def _extract_reasoning_delta(delta: dict[str, Any]) -> str:
        candidates = [
            delta.get("reasoning"),
            delta.get("reasoning_content"),
            delta.get("thinking"),
        ]
        for candidate in candidates:
            text = VolcengineProvider._coerce_reasoning_text(candidate)
            if text:
                return text
        return ""

    @staticmethod
    def _coerce_reasoning_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("text", "content", "reasoning"):
                item = value.get(key)
                if isinstance(item, str) and item:
                    return item
            return ""
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                text = VolcengineProvider._coerce_reasoning_text(item)
                if text:
                    parts.append(text)
            return "".join(parts)
        return ""

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

    def _post_stream_json(self, path: str, payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "text/event-stream",
            },
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    yield json.loads(data)
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
            parsed_arguments, parse_error = _parse_tool_arguments(arguments)
            if parse_error is not None:
                tool_name = function.get("name") or "unknown_tool"
                error_message = f"Malformed tool call arguments for {tool_name}: {parse_error}"
                return AgentResponse(
                    text=message.get("content") or error_message,
                    tool_calls=[],
                    finish="other",
                    model=ModelRef(provider_id="volcengine", model_id=payload.get("model", "unknown")),
                    tokens=_usage_from_payload(payload.get("usage", {})),
                    error=MessageError(
                        code="malformed_tool_arguments",
                        message=error_message,
                        details={
                            "tool_name": tool_name,
                            "arguments_preview": arguments[:500],
                        },
                    ),
                    raw=payload,
                )
            tool_calls.append(
                ToolCall(
                    id=item["id"],
                    name=function["name"],
                    arguments=parsed_arguments,
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


def _parse_tool_arguments(raw: str) -> tuple[dict[str, Any], str | None]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, str(exc)
    if not isinstance(parsed, dict):
        return {}, f"expected JSON object, got {type(parsed).__name__}"
    return parsed, None


def _usage_from_payload(usage: dict[str, Any]) -> TokenUsage:
    return TokenUsage(
        input=usage.get("prompt_tokens", 0),
        output=usage.get("completion_tokens", 0),
        reasoning=usage.get("reasoning_tokens", 0),
        cache_read=usage.get("prompt_cache_hit_tokens", 0),
        cache_write=usage.get("prompt_cache_miss_tokens", 0),
    )


def _map_openai_finish_reason(value: str | None) -> str:
    mapping = {
        "stop": "stop",
        "length": "length",
        "content_filter": "content-filter",
        "tool_calls": "tool-calls",
    }
    return mapping.get(value or "", "other")
