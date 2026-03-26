from __future__ import annotations

from openagent.domain.messages import Message, ToolCall


def serialize_message(message: Message) -> dict:
    return {
        "role": message.role,
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
    }


def deserialize_message(payload: dict) -> Message:
    return Message(
        role=payload["role"],
        content=payload["content"],
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
    )
