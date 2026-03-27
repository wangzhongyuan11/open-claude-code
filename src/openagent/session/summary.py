from __future__ import annotations

from openagent.domain.messages import Message


def summarize_messages(messages: list[Message]) -> str:
    if not messages:
        return "No prior context."

    user_requests: list[str] = []
    assistant_outcomes: list[str] = []
    reasoning_notes: list[str] = []
    tool_activity: list[str] = []
    relevant_paths: list[str] = []

    for message in messages:
        if message.role == "user":
            text = _message_text(message)
            if text:
                user_requests.append(text)
            continue

        if message.role == "assistant":
            for part in message.parts:
                if part.type == "reasoning" and isinstance(part.content, str) and part.content.strip():
                    reasoning_notes.append(part.content.strip())
                if part.type == "tool" and isinstance(part.content, dict):
                    name = part.content.get("name")
                    arguments = part.content.get("arguments", {})
                    path = arguments.get("path")
                    if name:
                        activity = name
                        if path:
                            activity += f"({path})"
                        tool_activity.append(activity)
                        if path:
                            relevant_paths.append(str(path))
            text = _message_text(message)
            if text:
                assistant_outcomes.append(text)
            continue

        if message.role == "tool":
            if message.name:
                tool_activity.append(message.name)
            tool_part = next((part for part in message.parts if part.type == "tool" and isinstance(part.content, dict)), None)
            if tool_part:
                path = tool_part.content.get("path") or tool_part.content.get("source_path")
                if path:
                    relevant_paths.append(str(path))

    lines: list[str] = ["Conversation summary:"]
    if user_requests:
        lines.append("Goals / requests:")
        lines.extend(f"- {item[:200]}" for item in user_requests[-5:])
    if tool_activity:
        lines.append("Tool activity:")
        lines.extend(f"- {item}" for item in _dedupe(tool_activity)[-8:])
    if relevant_paths:
        lines.append("Relevant paths:")
        lines.extend(f"- {item}" for item in _dedupe(relevant_paths)[-8:])
    if reasoning_notes:
        lines.append("Reasoning notes:")
        lines.extend(f"- {item[:160]}" for item in reasoning_notes[-4:])
    if assistant_outcomes:
        lines.append("Latest outcomes:")
        lines.extend(f"- {item[:200]}" for item in assistant_outcomes[-4:])
    return "\n".join(lines)


def _message_text(message: Message) -> str:
    if message.content.strip():
        return message.content.strip()
    for part in message.parts:
        if part.type in {"text", "reasoning"} and isinstance(part.content, str) and part.content.strip():
            return part.content.strip()
    return ""


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
