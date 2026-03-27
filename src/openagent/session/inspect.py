from __future__ import annotations

import json

from openagent.domain.messages import Message
from openagent.domain.session import Session


def build_session_inspect(session: Session, limit: int = 12) -> dict:
    recent_messages = session.messages[-limit:]
    return {
        "session_id": session.id,
        "title": session.title,
        "directory": session.directory or session.workspace,
        "summary_present": session.summary is not None,
        "summary_preview": session.summary.text[:240] if session.summary else None,
        "status": {
            "state": session.status.state,
            "retry_count": session.status.retry_count,
            "last_error": session.status.last_error,
            "recovery_hint": session.status.recovery_hint,
        },
        "metadata": {
            key: session.metadata.get(key)
            for key in [
                "last_finish_reason",
                "last_loop_unstable",
                "last_loop_steps",
                "last_loop_tool_calls",
                "last_prompt_notes",
                "prompt_token_estimate",
                "compacted_token_estimate",
                "prompt_window_message_count",
                "compaction_mode",
            ]
        },
        "recent_messages": [_inspect_message(message) for message in recent_messages],
    }


def format_session_inspect(session: Session, limit: int = 12) -> str:
    return json.dumps(build_session_inspect(session, limit=limit), ensure_ascii=False, indent=2)


def format_session_replay(session: Session) -> str:
    lines: list[str] = []
    turn = 0
    for message in session.messages:
        if message.role == "user":
            turn += 1
            lines.append(f"Turn {turn}")
            lines.append(f"  User: {message.content}")
            continue
        if message.role == "assistant":
            finish = f" finish={message.finish}" if message.finish else ""
            lines.append(f"  Assistant:{finish} {message.content}".rstrip())
            tool_requests = [part for part in message.parts if part.type == "tool" and isinstance(part.content, dict)]
            for part in tool_requests:
                lines.append(
                    f"    ToolRequest: {part.content.get('name')} {json.dumps(part.content.get('arguments', {}), ensure_ascii=False)}"
                )
            continue
        if message.role == "tool":
            lines.append(f"  ToolResult: {message.name} -> {message.content[:200]}")
    return "\n".join(lines) if lines else "(empty session)"


def _inspect_message(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "parent_id": message.parent_id,
        "agent": message.agent,
        "finish": message.finish,
        "content_preview": message.content[:200],
        "parts": [
            {
                "type": part.type,
                "state": part.state,
                "preview": _part_preview(part.content),
            }
            for part in message.parts
        ],
    }


def _part_preview(content) -> str:
    if isinstance(content, str):
        return content[:160]
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)[:160]
    return str(content)[:160]
