from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from openagent.domain.messages import Message, Part
from openagent.domain.session import Session, SessionSummary, utc_now_iso
from openagent.session.summary import summarize_messages


@dataclass(slots=True)
class CompactionPlan:
    changed: bool
    compacted_messages: list[Message]
    recent_messages: list[Message]
    estimated_tokens: int
    compacted_tokens: int
    overflow_by_count: bool = False
    overflow_by_tokens: bool = False
    recent_tools: list[str] = field(default_factory=list)
    recent_files: list[str] = field(default_factory=list)


def estimate_part_tokens(part: Part) -> int:
    if isinstance(part.content, str):
        return max(1, ceil(len(part.content) / 4))
    if isinstance(part.content, dict):
        size = sum(len(str(value)) for value in part.content.values())
        return max(1, ceil(size / 4))
    return 1


def estimate_message_tokens(message: Message) -> int:
    if message.parts:
        return sum(estimate_part_tokens(part) for part in message.parts) + 8
    return max(1, ceil(len(message.content) / 4)) + 8


def plan_compaction(
    session: Session,
    max_messages: int,
    keep_recent: int = 8,
    max_prompt_tokens: int = 12_000,
) -> CompactionPlan:
    if not session.messages:
        return CompactionPlan(False, [], [], 0, 0, False, False, [], [])

    total_tokens = sum(estimate_message_tokens(message) for message in session.messages)
    overflow_by_count = len(session.messages) > max_messages
    overflow_by_tokens = total_tokens > max_prompt_tokens
    if not overflow_by_count and not overflow_by_tokens:
        return CompactionPlan(
            False,
            [],
            list(session.messages),
            total_tokens,
            0,
            False,
            False,
            _recent_tools(session.messages),
            _recent_files(session.messages),
        )

    recent: list[Message] = []
    recent_tokens = 0
    for message in reversed(session.messages):
        token_count = estimate_message_tokens(message)
        must_keep = len(recent) < keep_recent
        within_budget = recent_tokens + token_count <= max_prompt_tokens
        if overflow_by_count and not overflow_by_tokens:
            within_budget = len(recent) < keep_recent
        if must_keep or within_budget:
            recent.append(message)
            recent_tokens += token_count
            continue
        break
    recent.reverse()

    compacted_count = max(0, len(session.messages) - len(recent))
    compacted_messages = session.messages[:compacted_count]
    compacted_tokens = total_tokens - recent_tokens
    return CompactionPlan(
        changed=bool(compacted_messages),
        compacted_messages=compacted_messages,
        recent_messages=recent,
        estimated_tokens=recent_tokens,
        compacted_tokens=max(0, compacted_tokens),
        overflow_by_count=overflow_by_count,
        overflow_by_tokens=overflow_by_tokens,
        recent_tools=_recent_tools(recent),
        recent_files=_recent_files(recent),
    )


def apply_compaction(session: Session, plan: CompactionPlan) -> bool:
    if not plan.changed:
        session.metadata["prompt_token_estimate"] = str(plan.estimated_tokens)
        return False
    summary_text = summarize_messages(plan.compacted_messages)
    session.summary = SessionSummary(
        text=summary_text,
        compacted_message_count=len(plan.compacted_messages),
        updated_at=utc_now_iso(),
    )
    session.metadata["compaction_count"] = str(int(session.metadata.get("compaction_count", "0")) + 1)
    session.metadata["prompt_token_estimate"] = str(plan.estimated_tokens)
    session.metadata["compacted_token_estimate"] = str(plan.compacted_tokens)
    session.metadata["prompt_window_message_count"] = str(len(plan.recent_messages))
    session.metadata["compaction_mode"] = _compaction_mode(plan)
    session.touch()
    return True


def maybe_compact(
    session: Session,
    max_messages: int,
    keep_recent: int = 8,
    max_prompt_tokens: int = 12_000,
) -> bool:
    return apply_compaction(
        session,
        plan_compaction(
            session,
            max_messages=max_messages,
            keep_recent=keep_recent,
            max_prompt_tokens=max_prompt_tokens,
        ),
    )


def summary_message(session: Session) -> Message | None:
    if not session.summary:
        return None
    return Message(
        role="assistant",
        agent="summary",
        content=f"[Session Summary]\n{session.summary.text}",
        finish="stop",
        parts=[
            Part(
                type="compaction",
                content={
                    "compacted_message_count": session.summary.compacted_message_count,
                    "updated_at": session.summary.updated_at,
                    "prompt_token_estimate": session.metadata.get("prompt_token_estimate"),
                    "compaction_mode": session.metadata.get("compaction_mode"),
                },
                state={"status": "applied"},
            ),
            Part(type="text", content=f"[Session Summary]\n{session.summary.text}"),
        ],
    )


def _recent_tools(messages: list[Message]) -> list[str]:
    tools: list[str] = []
    for message in messages[-8:]:
        for part in message.parts:
            if part.type == "tool" and isinstance(part.content, dict):
                name = part.content.get("name")
                if name:
                    tools.append(str(name))
    return _dedupe(tools)


def _recent_files(messages: list[Message]) -> list[str]:
    files: list[str] = []
    for message in messages[-8:]:
        for part in message.parts:
            if part.type == "tool" and isinstance(part.content, dict):
                path = part.content.get("arguments", {}).get("path")
                if path:
                    files.append(str(path))
    return _dedupe(files)


def _compaction_mode(plan: CompactionPlan) -> str:
    modes: list[str] = []
    if plan.overflow_by_count:
        modes.append("message-count")
    if plan.overflow_by_tokens:
        modes.append("token-budget")
    return "+".join(modes) or "none"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
