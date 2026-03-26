from __future__ import annotations

from openagent.domain.messages import Message, MessageError, ModelRef, Part, TokenUsage, ToolCall, new_id, utc_now_iso


def serialize_message(message: Message) -> dict:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "parent_id": message.parent_id,
        "agent": message.agent,
        "model": serialize_model(message.model),
        "tokens": serialize_tokens(message.tokens),
        "cost": message.cost,
        "finish": message.finish,
        "error": serialize_error(message.error),
        "created_at": message.created_at,
        "completed_at": message.completed_at,
        "content": message.content,
        "tool_call_id": message.tool_call_id,
        "name": message.name,
        "tool_calls": [
            {
                "id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            }
            for tool_call in message.tool_calls
        ],
        "parts": [
            {
                "id": part.id,
                "type": part.type,
                "content": part.content,
                "state": part.state,
                "created_at": part.created_at,
            }
            for part in message.parts
        ],
    }


def deserialize_message(payload: dict) -> Message:
    return Message(
        id=payload.get("id") or payload.get("message_id") or new_id(),
        session_id=payload.get("session_id"),
        role=payload["role"],
        parent_id=payload.get("parent_id"),
        agent=payload.get("agent"),
        model=deserialize_model(payload.get("model")),
        tokens=deserialize_tokens(payload.get("tokens")),
        cost=payload.get("cost", 0.0),
        finish=payload.get("finish"),
        error=deserialize_error(payload.get("error")),
        created_at=payload.get("created_at") or payload.get("time", {}).get("created") or utc_now_iso(),
        completed_at=payload.get("completed_at") or payload.get("time", {}).get("completed"),
        content=payload.get("content", ""),
        tool_call_id=payload.get("tool_call_id"),
        name=payload.get("name"),
        tool_calls=[
            ToolCall(
                id=tool_call["id"],
                name=tool_call["name"],
                arguments=tool_call["arguments"],
            )
            for tool_call in payload.get("tool_calls", [])
        ],
        parts=[
            Part(
                id=part.get("id") or new_id(),
                type=part["type"],
                content=part.get("content"),
                state=part.get("state", {}),
                created_at=part.get("created_at") or utc_now_iso(),
            )
            for part in payload.get("parts", [])
        ],
    )


def serialize_model(model: ModelRef | None) -> dict | None:
    if model is None:
        return None
    return {
        "provider_id": model.provider_id,
        "model_id": model.model_id,
        "variant": model.variant,
    }


def deserialize_model(payload: dict | None) -> ModelRef | None:
    if not payload:
        return None
    return ModelRef(
        provider_id=payload["provider_id"],
        model_id=payload["model_id"],
        variant=payload.get("variant"),
    )


def serialize_tokens(tokens: TokenUsage) -> dict:
    return {
        "input": tokens.input,
        "output": tokens.output,
        "reasoning": tokens.reasoning,
        "cache": {
            "read": tokens.cache_read,
            "write": tokens.cache_write,
        },
    }


def deserialize_tokens(payload: dict | None) -> TokenUsage:
    if not payload:
        return TokenUsage()
    cache = payload.get("cache", {})
    return TokenUsage(
        input=payload.get("input", 0),
        output=payload.get("output", 0),
        reasoning=payload.get("reasoning", 0),
        cache_read=cache.get("read", 0),
        cache_write=cache.get("write", 0),
    )


def serialize_error(error: MessageError | None) -> dict | None:
    if error is None:
        return None
    return {
        "code": error.code,
        "message": error.message,
        "details": error.details,
    }


def deserialize_error(payload: dict | None) -> MessageError | None:
    if not payload:
        return None
    return MessageError(
        code=payload.get("code", "unknown"),
        message=payload.get("message", ""),
        details=payload.get("details", {}),
    )
