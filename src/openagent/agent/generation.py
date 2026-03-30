from __future__ import annotations

import re
from dataclasses import dataclass

from openagent.agent.profile import AgentProfile
from openagent.permission.models import PermissionRule


RESERVED_AGENT_NAMES = {
    "build",
    "plan",
    "general",
    "explore",
    "title",
    "summary",
    "compaction",
    "generate",
}


@dataclass(slots=True)
class GeneratedAgentPayload:
    identifier: str
    when_to_use: str
    system_prompt: str


def sanitize_identifier(raw: str, existing: set[str]) -> str:
    normalized = raw.strip().lower()
    normalized = re.sub(r"[^a-z0-9-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    if not normalized:
        normalized = "custom-agent"
    if normalized in RESERVED_AGENT_NAMES:
        normalized = f"{normalized}-custom"
    candidate = normalized
    counter = 2
    while candidate in existing or candidate in RESERVED_AGENT_NAMES:
        candidate = f"{normalized}-{counter}"
        counter += 1
    return candidate


def build_safe_profile_from_generated(
    payload: GeneratedAgentPayload,
    *,
    existing_names: set[str],
    description_seed: str,
) -> AgentProfile:
    identifier = sanitize_identifier(payload.identifier, existing=existing_names)
    description = payload.when_to_use.strip() or f"Use this agent when {description_seed.strip()}."
    prompt = payload.system_prompt.strip()
    lowered = f"{description_seed}\n{description}\n{prompt}".lower()

    mode = "all"
    allowed_tools = None
    permission_rules: list[PermissionRule] = []
    if any(token in lowered for token in ["subagent", "子代理", "委派", "delegated", "delegate"]):
        mode = "subagent"
    if any(token in lowered for token in ["primary", "主代理", "main agent"]):
        mode = "primary"

    readonly_signal = any(
        token in lowered
        for token in [
            "只读",
            "read-only",
            "不修改",
            "不编辑",
            "review",
            "审查",
            "分析",
            "inspect",
            "explore",
            "搜索",
        ]
    )
    if readonly_signal:
        allowed_tools = {
            "read_file",
            "read_file_range",
            "read",
            "list_files",
            "ls",
            "glob",
            "grep",
            "codesearch",
            "read_symbol",
            "webfetch",
            "websearch",
            "skill",
            "lsp",
            "todoread",
            "question",
            "batch",
            "background_task",
        }
        for tool in {
            "ensure_dir",
            "write_file",
            "write",
            "append_file",
            "edit_file",
            "edit",
            "replace_all",
            "insert_text",
            "multiedit",
            "apply_patch",
            "patch",
            "bash",
            "background_task",
            "todowrite",
        }:
            permission_rules.append(
                PermissionRule(
                    agent=identifier,
                    permission=f"tool.{tool}",
                    pattern="*",
                    action="deny",
                    source="generated-readonly",
                )
            )

    inherits_default_prompt = not readonly_signal
    if readonly_signal and "do not modify" not in prompt.lower() and "不要修改" not in prompt:
        prompt = prompt.rstrip() + "\n\nDo not modify files or run shell commands that change system state."

    return AgentProfile(
        name=identifier,
        description=description,
        mode=mode,  # type: ignore[arg-type]
        native=False,
        prompt=prompt,
        steps=10,
        inherits_default_prompt=inherits_default_prompt,
        allowed_tools=allowed_tools,
        permission_rules=permission_rules,
    )
