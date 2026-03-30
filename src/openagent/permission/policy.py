from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openagent.agent.profile import AgentProfile
from openagent.domain.events import Event
from openagent.domain.messages import Message, Part
from openagent.extensions.base import ExtensionContext, PermissionDecision, PermissionPolicy
from openagent.permission.evaluate import evaluate_rules
from openagent.permission.models import PermissionReply, PermissionRequest, PermissionRule
from openagent.session.store import SessionStore


READ_ONLY_TOOLS = {
    "read_file",
    "read_file_range",
    "read",
    "list_files",
    "ls",
    "glob",
    "grep",
    "codesearch",
    "read_symbol",
    "todoread",
    "question",
    "skill",
    "lsp",
}

WRITE_TOOLS = {
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
}

SHELL_TOOLS = {"bash", "background_task"}
NETWORK_TOOLS = {"webfetch", "websearch"}
DELEGATE_TOOLS = {"delegate", "task"}
TODO_WRITE_TOOLS = {"todowrite"}


@dataclass(slots=True)
class PermissionContextDescriptor:
    permission: str
    pattern: str
    metadata: dict[str, Any]


class SessionPermissionPolicy(PermissionPolicy):
    def __init__(
        self,
        store: SessionStore,
        agent_profile: AgentProfile,
        *,
        yolo: bool = False,
        event_bus=None,
    ) -> None:
        self.store = store
        self.agent_profile = agent_profile
        self.yolo = yolo
        self.event_bus = event_bus

    def check(self, context: ExtensionContext) -> PermissionDecision:
        descriptor = self._describe(context)
        session_id = context.tool_context.session_id or "unknown"
        agent_name = context.tool_context.agent_name or self.agent_profile.name

        if self._violates_readonly_delegate(context, descriptor):
            return PermissionDecision(
                allowed=False,
                action="deny",
                reason="readonly agent may only delegate to readonly subagents.",
            )

        rulesets = [
            self._default_rules_for_agent(self.agent_profile),
            self._persisted_rules(session_id),
        ]
        resolved = evaluate_rules(agent_name, descriptor.permission, descriptor.pattern, rulesets)
        if resolved.action == "allow":
            return PermissionDecision(allowed=True, action="allow", reason=resolved.source)
        request = PermissionRequest(
            session_id=session_id,
            agent_name=agent_name,
            tool_name=context.tool_name,
            permission=descriptor.permission,
            pattern=descriptor.pattern,
            metadata=descriptor.metadata,
            message_id=context.tool_context.message_id,
            tool_call_id=context.tool_context.tool_call_id,
        )
        if resolved.action == "deny":
            return PermissionDecision(
                allowed=False,
                action="deny",
                reason=f"permission denied by {resolved.source}: {descriptor.permission} -> {descriptor.pattern}",
                request=request,
            )
        return PermissionDecision(
            allowed=False,
            action="ask",
            reason="approval required",
            request=request,
        )

    def record_request(self, request: PermissionRequest) -> None:
        self._append_permission_message(
            request.session_id,
            content=f"[Permission] ask {request.tool_name} {request.pattern}",
            state="asked",
            payload=request.to_dict(),
        )
        self._emit("permission.asked", request.to_dict())

    def record_reply(self, request: PermissionRequest, reply: PermissionReply, *, yolo: bool = False) -> None:
        if reply == "always":
            rule = PermissionRule(
                agent=request.agent_name,
                permission=request.permission,
                pattern=request.pattern,
                action="allow",
                source="session-always",
            )
            self.store.update(request.session_id, lambda session: _append_rule(session.permission, rule))
        payload = {
            "request_id": request.id,
            "tool_name": request.tool_name,
            "permission": request.permission,
            "pattern": request.pattern,
            "reply": reply,
            "yolo": yolo,
        }
        self._append_permission_message(
            request.session_id,
            content=f"[Permission] {reply} {request.tool_name} {request.pattern}",
            state="approved" if reply in {"once", "always"} else "rejected",
            payload=payload,
        )
        self._emit(
            "permission.replied",
            {
                "session_id": request.session_id,
                "request_id": request.id,
                "reply": reply,
                "yolo": yolo,
            },
        )

    def set_yolo(self, session_id: str, enabled: bool) -> None:
        self.yolo = enabled

        def updater(session) -> None:
            permission = _ensure_permission_payload(session.permission)
            permission["yolo"] = enabled
            session.permission = permission
            session.metadata["yolo_mode"] = "true" if enabled else "false"
            session.touch()

        self.store.update(session_id, updater)

    def yolo_enabled(self, session_id: str) -> bool:
        try:
            session = self.store.load(session_id)
        except FileNotFoundError:
            return self.yolo
        permission = _ensure_permission_payload(session.permission)
        return bool(permission.get("yolo", self.yolo))

    def _persisted_rules(self, session_id: str) -> list[PermissionRule]:
        try:
            session = self.store.load(session_id)
        except FileNotFoundError:
            return []
        permission = _ensure_permission_payload(session.permission)
        rules = permission.get("rules", [])
        return [PermissionRule.from_dict(item) for item in rules if isinstance(item, dict)]

    def _default_rules_for_agent(self, profile: AgentProfile) -> list[PermissionRule]:
        if profile.permission_rules:
            return list(profile.permission_rules)
        readonly = _is_readonly_profile(profile)
        rules: list[PermissionRule] = []
        if readonly:
            for tool in WRITE_TOOLS | SHELL_TOOLS | TODO_WRITE_TOOLS:
                rules.append(PermissionRule(agent=profile.name, permission=f"tool.{tool}", pattern="*", action="deny", source="agent-readonly"))
            for tool in DELEGATE_TOOLS:
                rules.append(PermissionRule(agent=profile.name, permission=f"tool.{tool}", pattern="*", action="ask", source="agent-readonly"))
            for tool in NETWORK_TOOLS:
                rules.append(PermissionRule(agent=profile.name, permission=f"tool.{tool}", pattern="*", action="ask", source="agent-readonly"))
            for tool in READ_ONLY_TOOLS:
                rules.append(PermissionRule(agent=profile.name, permission=f"tool.{tool}", pattern="*", action="allow", source="agent-default"))
            return rules

        for tool in READ_ONLY_TOOLS | DELEGATE_TOOLS:
            rules.append(PermissionRule(agent=profile.name, permission=f"tool.{tool}", pattern="*", action="allow", source="agent-default"))
        for tool in WRITE_TOOLS | SHELL_TOOLS | NETWORK_TOOLS | TODO_WRITE_TOOLS:
            rules.append(PermissionRule(agent=profile.name, permission=f"tool.{tool}", pattern="*", action="ask", source="agent-default"))
        rules.append(PermissionRule(agent=profile.name, permission="tool.batch", pattern="*", action="ask", source="agent-default"))
        return rules

    def _describe(self, context: ExtensionContext) -> PermissionContextDescriptor:
        name = context.tool_name
        arguments = context.arguments
        if name in READ_ONLY_TOOLS:
            return PermissionContextDescriptor(permission=f"tool.{name}", pattern=_path_pattern(arguments, context.tool_context.workspace), metadata={"kind": "read"})
        if name in WRITE_TOOLS:
            return PermissionContextDescriptor(permission=f"tool.{name}", pattern=_path_pattern(arguments, context.tool_context.workspace), metadata={"kind": "write"})
        if name == "bash":
            command = str(arguments.get("command", ""))
            return PermissionContextDescriptor(permission="tool.bash", pattern=_command_pattern(command), metadata={"command": command})
        if name == "background_task":
            action = str(arguments.get("action", "start"))
            if action != "start":
                return PermissionContextDescriptor(permission="tool.background_task.inspect", pattern=action, metadata={"action": action})
            command = str(arguments.get("command", ""))
            return PermissionContextDescriptor(permission="tool.background_task", pattern=_command_pattern(command), metadata={"command": command})
        if name in NETWORK_TOOLS:
            pattern = str(arguments.get("url") or arguments.get("query") or "*")
            return PermissionContextDescriptor(permission=f"tool.{name}", pattern=pattern, metadata={"kind": "network"})
        if name in DELEGATE_TOOLS:
            target = str(arguments.get("subagent_type") or arguments.get("agent_name") or "general")
            return PermissionContextDescriptor(permission=f"tool.{name}", pattern=target, metadata={"target_agent": target})
        if name in TODO_WRITE_TOOLS:
            return PermissionContextDescriptor(permission=f"tool.{name}", pattern="session:todos", metadata={"kind": "session"})
        return PermissionContextDescriptor(permission=f"tool.{name}", pattern="*", metadata={})

    def _violates_readonly_delegate(self, context: ExtensionContext, descriptor: PermissionContextDescriptor) -> bool:
        if context.tool_name not in DELEGATE_TOOLS:
            return False
        if not _is_readonly_profile(self.agent_profile):
            return False
        target = descriptor.metadata.get("target_agent", "general")
        return str(target) not in {"plan", "explore"}

    def _append_permission_message(self, session_id: str, *, content: str, state: str, payload: dict[str, Any]) -> None:
        def updater(session) -> None:
            permission = _ensure_permission_payload(session.permission)
            permission["last_request"] = payload.get("request_id") or payload.get("id") or ""
            session.permission = permission
            session.metadata["last_permission_state"] = state
            session.messages.append(
                Message(
                    role="assistant",
                    agent="session-op",
                    content=content,
                    finish="stop",
                    parts=[
                        Part(
                            type="permission",
                            content=payload,
                            state={"status": state},
                        )
                    ],
                )
            )
            session.touch()

        self.store.update(session_id, updater)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event(type=event_type, payload=payload))


def _append_rule(permission_payload: dict[str, Any], rule: PermissionRule) -> None:
    permission = _ensure_permission_payload(permission_payload)
    rules = permission.setdefault("rules", [])
    rules.append(rule.to_dict())


def _ensure_permission_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("rules", [])
    payload.setdefault("yolo", False)
    return payload


def _path_pattern(arguments: dict[str, Any], workspace: Path) -> str:
    path = arguments.get("path")
    if not path:
        return "*"
    try:
        return str(Path(path).resolve().relative_to(workspace))
    except Exception:
        return str(path)


def _command_pattern(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except Exception:
        return command or "*"
    if not tokens:
        return "*"
    prefix = [tokens[0]]
    if len(tokens) > 1 and not tokens[1].startswith("-"):
        prefix.append(tokens[1])
    return " ".join(prefix)


def _is_readonly_profile(profile: AgentProfile) -> bool:
    if profile.allowed_tools is None:
        return False
    return not any(tool in profile.allowed_tools for tool in WRITE_TOOLS | SHELL_TOOLS | TODO_WRITE_TOOLS)
