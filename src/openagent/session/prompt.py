from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace

from openagent.domain.messages import Message, Part
from openagent.domain.session import Session
from openagent.session.compaction import CompactionPlan, estimate_message_tokens, summary_message
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
    trimmed_recent, trimmed_count = build_recent_prompt_window(plan.recent_messages)
    prompt_messages.extend(trimmed_recent)
    notes: list[str] = []
    if historical_summary:
        notes.append("summary-included")
    if context_note:
        notes.append("context-note-included")
    if trimmed_count:
        notes.append(f"prompt-window-trimmed:{trimmed_count}")
    return PromptContext(
        system_prompt=build_system_prompt(session, base_system_prompt),
        messages=prompt_messages,
        estimated_tokens=sum(estimate_message_tokens(message) for message in prompt_messages),
        notes=notes,
    )


def build_context_note(plan: CompactionPlan) -> Message | None:
    messages = plan.recent_messages
    tool_states: list[str] = []
    recent_files: list[str] = list(plan.recent_files)
    recent_turns: list[str] = []
    recent_patches: list[str] = []
    recent_snapshots: list[str] = []
    retry_notes: list[str] = []
    background_notes: list[str] = []
    agent_notes: list[str] = []
    permission_notes: list[str] = []
    for message in messages[-6:]:
        if message.role == "assistant" and message.finish:
            recent_turns.append(f"assistant finish={message.finish}")
        for part in message.parts:
            if part.type == "agent" and isinstance(part.content, dict):
                source = part.content.get("source_agent")
                target = part.content.get("target_agent")
                action = part.content.get("action")
                reason = part.content.get("reason")
                line = f"{source} -> {target} ({action})"
                if reason:
                    line += f" reason={reason}"
                agent_notes.append(line)
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
            elif part.type == "patch" and isinstance(part.content, str):
                recent_patches.append(_patch_summary(part.content))
            elif part.type == "snapshot" and isinstance(part.content, dict):
                ref = part.content.get("ref")
                path = part.content.get("path")
                if ref:
                    label = str(ref)
                    if path:
                        label += f" ({path})"
                    recent_snapshots.append(label)
            elif part.type == "retry" and isinstance(part.content, dict):
                retry_notes.append(f"attempt={part.content.get('attempt')} delay_ms={part.content.get('delay_ms')}")
            elif part.type == "background-task" and isinstance(part.content, dict):
                task_id = part.content.get("task_id")
                status = part.content.get("status")
                title = part.content.get("title") or task_id
                exit_code = part.content.get("exit_code")
                summary = part.content.get("output_summary")
                line = f"{title} ({task_id}) -> {status}"
                if exit_code not in (None, ""):
                    line += f" exit={exit_code}"
                if summary:
                    line += f" summary={summary}"
                background_notes.append(line)
            elif part.type == "permission" and isinstance(part.content, dict):
                tool_name = part.content.get("tool_name")
                reply = part.content.get("reply")
                pattern = part.content.get("pattern")
                status = part.state.get("status")
                if tool_name:
                    line = f"{tool_name} -> {pattern}"
                    if reply:
                        line += f" reply={reply}"
                    if status:
                        line += f" status={status}"
                    permission_notes.append(line)
    if not tool_states and not recent_files and not recent_turns and not recent_patches and not recent_snapshots and not retry_notes and not background_notes and not agent_notes and not permission_notes:
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
    if recent_patches:
        lines.append("Recent patches:")
        lines.extend(f"- {item}" for item in _dedupe(recent_patches)[-4:])
    if recent_snapshots:
        lines.append("Recent snapshots:")
        lines.extend(f"- {item}" for item in _dedupe(recent_snapshots)[-4:])
    if retry_notes:
        lines.append("Retry notes:")
        lines.extend(f"- {item}" for item in _dedupe(retry_notes)[-4:])
    if background_notes:
        lines.append("Background tasks:")
        lines.extend(f"- {item}" for item in _dedupe(background_notes)[-6:])
    if agent_notes:
        lines.append("Agent handoffs:")
        lines.extend(f"- {item}" for item in _dedupe(agent_notes)[-6:])
    if permission_notes:
        lines.append("Recent permissions:")
        lines.extend(f"- {item}" for item in _dedupe(permission_notes)[-6:])
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


def _patch_summary(diff_text: str) -> str:
    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return f"+{added}/-{removed}"


def build_recent_prompt_window(messages: list[Message], max_chars_per_part: int = 600) -> tuple[list[Message], int]:
    trimmed_messages: list[Message] = []
    trimmed_count = 0
    for message in messages:
        trimmed_message, changed = _trim_message(message, max_chars_per_part=max_chars_per_part)
        trimmed_messages.append(trimmed_message)
        if changed:
            trimmed_count += 1
    return trimmed_messages, trimmed_count


def _trim_message(message: Message, max_chars_per_part: int) -> tuple[Message, bool]:
    changed = False
    trimmed_parts: list[Part] = []
    for part in message.parts:
        trimmed_part = replace(part)
        if part.type in {"text", "reasoning", "patch"} and isinstance(part.content, str):
            new_content, was_trimmed = _trim_text(part.content, max_chars_per_part)
            trimmed_part.content = new_content
            changed = changed or was_trimmed
        elif part.type == "file" and isinstance(part.content, dict):
            trimmed_content = dict(part.content)
            text = trimmed_content.get("content")
            if isinstance(text, str):
                new_content, was_trimmed = _trim_text(text, max_chars_per_part)
                trimmed_content["content"] = new_content
                changed = changed or was_trimmed
            trimmed_part.content = trimmed_content
        elif part.type == "tool" and isinstance(part.content, dict):
            trimmed_content = dict(part.content)
            output = trimmed_content.get("output")
            if isinstance(output, str):
                new_output, was_trimmed = _trim_text(output, max_chars_per_part)
                trimmed_content["output"] = new_output
                changed = changed or was_trimmed
            trimmed_part.content = trimmed_content
        trimmed_parts.append(trimmed_part)
    trimmed_message = replace(message, parts=trimmed_parts, content="")
    trimmed_message.content = trimmed_message._derive_content_from_parts()
    return trimmed_message, changed


def _trim_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n...[truncated {omitted} chars]", True
