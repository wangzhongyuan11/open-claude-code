from __future__ import annotations

from dataclasses import dataclass, field

from openagent.domain.messages import Message, Part
from openagent.domain.session import Session
from openagent.session.compaction import CompactionPlan, summary_message
from openagent.session.system import build_system_prompt


@dataclass(slots=True)
class PromptContext:
    system_prompt: str
    messages: list[Message]
    estimated_tokens: int = 0
    notes: list[str] = field(default_factory=list)


def build_prompt_context(
    session: Session,
    base_system_prompt: str,
    plan: CompactionPlan,
) -> PromptContext:
    prompt_messages: list[Message] = []
    historical_summary = summary_message(session)
    if historical_summary:
        prompt_messages.append(historical_summary)
    context_note = build_context_note(plan)
    if context_note:
        prompt_messages.append(context_note)
    prompt_messages.extend(plan.recent_messages)
    notes: list[str] = []
    if historical_summary:
        notes.append("summary-included")
    if context_note:
        notes.append("context-note-included")
    return PromptContext(
        system_prompt=build_system_prompt(session, base_system_prompt),
        messages=prompt_messages,
        estimated_tokens=plan.estimated_tokens,
        notes=notes,
    )


def build_context_note(plan: CompactionPlan) -> Message | None:
    messages = plan.recent_messages
    tool_states: list[str] = []
    recent_files: list[str] = list(plan.recent_files)
    recent_turns: list[str] = []
    for message in messages[-6:]:
        if message.role == "assistant" and message.finish:
            recent_turns.append(f"assistant finish={message.finish}")
        for part in message.parts:
            if part.type == "tool" and isinstance(part.content, dict):
                name = part.content.get("name")
                path = part.content.get("arguments", {}).get("path")
                status = part.state.get("status")
                if name:
                    line = name
                    if path:
                        line += f"({path})"
                        recent_files.append(str(path))
                    if status:
                        line += f" -> {status}"
                    tool_states.append(line)
    if not tool_states and not recent_files and not recent_turns:
        return None
    lines = ["[Runtime Context]"]
    lines.append(
        f"Window: {len(plan.recent_messages)} messages, ~{plan.estimated_tokens} prompt tokens."
    )
    if plan.overflow_by_count or plan.overflow_by_tokens:
        causes: list[str] = []
        if plan.overflow_by_count:
            causes.append("message-count")
        if plan.overflow_by_tokens:
            causes.append("token-budget")
        lines.append("Compaction trigger: " + ", ".join(causes))
    if recent_turns:
        lines.append("Recent turn states:")
        lines.extend(f"- {item}" for item in _dedupe(recent_turns)[-6:])
    if tool_states:
        lines.append("Recent tool states:")
        lines.extend(f"- {item}" for item in _dedupe(tool_states)[-6:])
    if recent_files:
        lines.append("Recent files:")
        lines.extend(f"- {item}" for item in _dedupe(recent_files)[-6:])
    text = "\n".join(lines)
    return Message(
        role="assistant",
        agent="context",
        content=text,
        finish="stop",
        parts=[
            Part(type="text", content=text),
        ],
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
