from __future__ import annotations

from openagent.domain.messages import Message


def summarize_messages(messages: list[Message]) -> str:
    if not messages:
        return "No prior context."

    user_requests: list[str] = []
    assistant_outcomes: list[str] = []
    tool_usage: list[str] = []

    for message in messages:
        if message.role == "user" and message.content.strip():
            user_requests.append(message.content.strip())
        elif message.role == "assistant" and message.content.strip():
            assistant_outcomes.append(message.content.strip())
        elif message.role == "tool" and message.name:
            tool_usage.append(message.name)

    lines: list[str] = ["Conversation summary:"]
    if user_requests:
        lines.append("User requests:")
        lines.extend(f"- {item[:160]}" for item in user_requests[-5:])
    if tool_usage:
        unique_tools = ", ".join(sorted(set(tool_usage)))
        lines.append(f"Tools used: {unique_tools}")
    if assistant_outcomes:
        lines.append("Latest outcomes:")
        lines.extend(f"- {item[:160]}" for item in assistant_outcomes[-5:])
    return "\n".join(lines)
