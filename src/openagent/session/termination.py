from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TerminationDecision:
    should_stop: bool
    reply: str
    reason: str


def detect_completion(
    user_text: str,
    tool_name: str,
    arguments: dict[str, Any],
    content: str,
    metadata: dict[str, Any],
) -> TerminationDecision | None:
    if _is_multistep_request(user_text):
        return None

    if tool_name in {"delegate", "task"}:
        return _delegate_completion(user_text, content)

    if tool_name in {"read_file", "read"}:
        decision = _read_completion(user_text, content)
        if decision:
            return decision
        decision = _edit_verification_completion(user_text, arguments, content)
        if decision:
            return decision
        decision = _write_verification_completion(user_text, arguments, content)
        if decision:
            return decision

    if tool_name in {"write_file", "append_file", "edit_file", "write", "edit", "apply_patch", "patch", "multiedit"}:
        decision = _write_or_edit_completion(user_text, tool_name, arguments, metadata)
        if decision:
            return decision

    return None


def _delegate_completion(user_text: str, content: str) -> TerminationDecision | None:
    delegate_intent = any(token in user_text for token in ["委托给子代理", "子代理完成", "delegate", "subagent"])
    direct_handoff = any(token in user_text for token in ["直接告诉", "只告诉", "告诉我结果", "完成后", "just tell me", "tell me the result"])
    if not delegate_intent or not direct_handoff:
        return None
    if "<delegate_result>" not in content:
        return None
    payload_text = content.replace("<delegate_result>", "").replace("</delegate_result>", "").strip()
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return TerminationDecision(True, content, "delegate-report")
    summary = payload.get("summary") or "子代理任务已完成。"
    touched = payload.get("touched_paths") or []
    verified = payload.get("verified_paths") or []
    suffix = []
    if touched:
        suffix.append("修改: " + ", ".join(touched[:3]))
    if verified:
        suffix.append("验证: " + ", ".join(verified[:3]))
    reply = summary
    if suffix:
        reply += "\n" + "\n".join(suffix)
    return TerminationDecision(True, reply, "delegate-report")


def _read_completion(user_text: str, content: str) -> TerminationDecision | None:
    if _requests_partial_read(user_text):
        return None
    if any(token in user_text for token in ["只回复其内容", "原样输出", "原样返回", "exact output"]):
        return TerminationDecision(True, content, "exact-read")
    return None


def _write_or_edit_completion(
    user_text: str,
    tool_name: str,
    arguments: dict[str, Any],
    metadata: dict[str, Any],
) -> TerminationDecision | None:
    path = str(metadata.get("path") or arguments.get("path") or "")
    after_content = metadata.get("after_content")
    if not isinstance(after_content, str):
        return None

    expected_content = _extract_expected_content(user_text)
    if tool_name in {"write_file", "append_file"} and expected_content is not None:
        if _normalize_ws(after_content) == _normalize_ws(expected_content):
            return TerminationDecision(True, f"已完成，已写入 {path}。", "write-satisfied")

    replace_pair = _extract_replace_pair(user_text)
    if tool_name in {"edit_file", "edit", "apply_patch", "patch", "multiedit"} and replace_pair is not None:
        old_text, new_text = replace_pair
        before_content = metadata.get("before_content")
        if isinstance(before_content, str):
            expected_after = before_content.replace(old_text, new_text, 1)
            if _normalize_ws(after_content) == _normalize_ws(expected_after):
                return TerminationDecision(True, f"已完成，已修改 {path}。", "edit-satisfied")
        if new_text in after_content and old_text not in after_content:
            return TerminationDecision(True, f"已完成，已修改 {path}。", "edit-satisfied")

    return None


def _edit_verification_completion(user_text: str, arguments: dict[str, Any], content: str) -> TerminationDecision | None:
    replace_pair = _extract_replace_pair(user_text)
    if replace_pair is None:
        return None
    old_text, new_text = replace_pair
    if new_text in content and old_text not in content:
        return TerminationDecision(True, content, "edit-verified")
    return None


def _write_verification_completion(user_text: str, arguments: dict[str, Any], content: str) -> TerminationDecision | None:
    expected_content = _extract_expected_content(user_text)
    if expected_content is None:
        return None
    if _normalize_ws(content) == _normalize_ws(expected_content):
        if "只回复其内容" in user_text or "原样输出" in user_text:
            return TerminationDecision(True, content, "write-verified")
        path = arguments.get("path")
        return TerminationDecision(True, f"已完成，文件内容已符合预期：{path}", "write-verified")
    return None


def _extract_expected_content(user_text: str) -> str | None:
    match = re.search(r"内容是(?:[:：])?\s*(.+)$", user_text, flags=re.S)
    if not match:
        return None
    return match.group(1).strip()


def _extract_replace_pair(user_text: str) -> tuple[str, str] | None:
    match = re.search(r"中的\s*(.+?)\s*改成\s*(.+?)(?:。)?$", user_text, flags=re.S)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.search(r"把\s*(.+?)\s*替换成\s*(.+?)(?:。)?$", user_text, flags=re.S)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None


def _normalize_ws(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _is_multistep_request(user_text: str) -> bool:
    return len(re.findall(r"(?m)^\s*\d+\.\s+", user_text)) >= 2


def _requests_partial_read(user_text: str) -> bool:
    return bool(
        re.search(r"前\s*\d+\s*行", user_text)
        or re.search(r"后\s*\d+\s*行", user_text)
        or "前几行" in user_text
        or "后几行" in user_text
        or "line " in user_text.lower()
    )
