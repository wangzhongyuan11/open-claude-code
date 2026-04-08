from __future__ import annotations

from pathlib import Path
import json
import time
from typing import Any, Callable

from openagent.agent.loop import AgentLoop
from openagent.agent.generation import GeneratedAgentPayload, build_safe_profile_from_generated
from openagent.agent.profile import AgentProfile
from openagent.agent.prompts import PROMPT_BUILD, compose_agent_prompt
from openagent.agent.registry import AgentRegistry, build_agent_registry
from openagent.agent.routing import RoutingDecision, decide_routing
from openagent.agent.store import AgentStore
from openagent.agent.subagent import SubagentManager
from openagent.config.settings import Settings
from openagent.domain.events import Event
from openagent.domain.messages import Message, MessageError, ModelRef, Part, TokenUsage
from openagent.domain.session import Session
from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.events.logger import get_logger
from openagent.lsp import LspManager
from openagent.mcp import McpGetPromptTool, McpManager, McpReadResourceTool, McpTool
from openagent.providers.base import BaseProvider
from openagent.providers.factory import build_provider
from openagent.permission.policy import SessionPermissionPolicy
from openagent.session.manager import SessionManager
from openagent.session.snapshot import SnapshotManager, build_snapshot_revert_message
from openagent.session.background import BackgroundTaskManager
from openagent.session.inspect import format_session_inspect, format_session_replay
from openagent.session.status import status_payload
from openagent.session.summary import summarize_messages
from openagent.session.system import build_system_prompt
from openagent.session.store import SessionStore
from openagent.session.task_validation import (
    looks_multistep,
    parse_multistep_requirements,
    validate_multistep_requirements,
)
from openagent.skill import SkillManager
from openagent.tools.builtin.bash import BashTool
from openagent.tools.builtin.background import BackgroundTaskTool
from openagent.tools.builtin.delegate import DelegateTool
from openagent.tools.builtin.edit import EditFileTool, InsertTextTool, MultiEditTool, ReplaceAllTool
from openagent.tools.builtin.files import AppendFileTool, EnsureDirTool, ListFilesTool, ReadFileTool, ReadFileRangeTool, WriteFileTool
from openagent.tools.builtin.integration import BatchTool, CodeSearchTool, LspTool, QuestionTool, ReadSymbolTool, SkillTool
from openagent.tools.builtin.patch import ApplyPatchTool
from openagent.tools.builtin.aliases import EditTool, PatchTool, ReadTool, TaskTool, TodoReadTool, TodoWriteTool, WriteTool
from openagent.tools.builtin.search import GlobTool, GrepTool, LsTool
from openagent.tools.builtin.web import WebFetchTool, WebSearchTool
from openagent.tools.registry import ToolRegistry


DEFAULT_SYSTEM_PROMPT = PROMPT_BUILD

TOOL_ENFORCEMENT_SUFFIX = """
Tool enforcement:
- This user request requires at least one real tool call before you can answer.
- If you do not obtain a tool result, you must not claim the task was completed.
- If a tool is unavailable or insufficient, say that explicitly instead of pretending the action succeeded.
"""

MULTISTEP_CONTINUATION_SUFFIX = """
This is a multi-step request and you stopped too early.
Continue executing the unfinished requirements in order.
Do not repeat steps that are already complete.
Only stop when every remaining requirement is finished and the final summary has been given.
"""

logger = get_logger(__name__)


class AgentRuntime:
    def __init__(
        self,
        provider: BaseProvider,
        workspace: Path,
        session_manager: SessionManager,
        session: Session,
        settings: Settings,
        event_bus: EventBus | None = None,
        provider_factory: Callable[[AgentProfile | str | None], BaseProvider] | None = None,
        agent_registry: AgentRegistry | None = None,
        agent_name: str | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.session_manager = session_manager
        self.session = session
        self.settings = settings
        self.event_bus = event_bus
        self.agent_store = AgentStore(settings.agent_root)
        self.agent_registry = agent_registry or build_agent_registry(settings, store=self.agent_store)
        requested_agent = agent_name or session.metadata.get("active_agent") or self.agent_registry.default_primary().name
        self.agent_profile = self.agent_registry.get(requested_agent)
        self.hidden_agents_enabled = provider_factory is not None
        self.provider_factory = provider_factory or (lambda profile=None: provider)
        self.provider = provider
        self.question_handler: Callable[[list[dict[str, Any]]], list[str]] | None = None
        self.permission_handler: Callable[[Any], str] | None = None
        self.background_tasks = BackgroundTaskManager(
            store=self.session_manager.store,
            workspace=self.workspace,
            event_bus=self.event_bus,
        )
        self.lsp_manager = LspManager(self.workspace, event_bus=self.event_bus) if self.settings.lsp_enabled else None
        self.skill_manager = SkillManager(self.workspace, extra_paths=self.settings.skill_paths)
        self.mcp_manager = (
            McpManager(self.workspace, config_paths=self.settings.mcp_config_paths, event_bus=self.event_bus)
            if self.settings.mcp_enabled
            else None
        )
        self.snapshot_manager = SnapshotManager(
            self.session_manager.store,
            self.workspace,
            enabled=self.settings.snapshot_enabled,
            event_bus=self.event_bus,
        )
        self.session.permission.setdefault("rules", [])
        self.session.permission.setdefault("yolo", self.settings.yolo_mode)
        self.session.metadata["active_agent"] = self.agent_profile.name
        self.session.metadata["yolo_mode"] = "true" if self.session.permission.get("yolo", self.settings.yolo_mode) else "false"
        self.session.metadata["snapshot_enabled"] = "true" if self.settings.snapshot_enabled else "false"
        self.session.touch()
        self.session_manager.store.save(self.session)
        if self.hidden_agents_enabled:
            self.session_manager.set_title_generator(self._generate_session_title)
            self.session_manager.set_compaction_summarizer(self._generate_compaction_summary)
        self.subagent_manager = self._build_subagent_manager()
        self.registry = self._build_registry_for_profile(self.agent_profile)
        self.loop = AgentLoop(
            provider=self.provider,
            tool_registry=self.registry,
            tool_context=ToolContext(
                workspace=self.workspace,
                session_id=self.session.id,
                agent_name=self.agent_profile.name,
                event_bus=self.event_bus,
                runtime_state=self._tool_runtime_state(self.agent_profile.name),
                permission=dict(self.session.permission),
            ),
            event_bus=self.event_bus,
        )

    @property
    def system_prompt(self) -> str:
        return self._system_prompt_for(self.agent_profile)

    def run_turn(
        self,
        user_text: str,
        stream_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        self._refresh_session()
        checklist_requirements = parse_multistep_requirements(user_text) if looks_multistep(user_text) else None
        routing = decide_routing(self.agent_profile, user_text)
        if routing.action == "switch" and routing.target_agent:
            self._auto_switch_agent(routing)
        if routing.action == "delegate" and routing.target_agent:
            return self._auto_delegate_turn(user_text, routing)
        self._emit("message.added", {"role": "user", "session_id": self.session.id})
        self.session_manager.append_message(
            self.session,
            Message(role="user", content=user_text),
            mark_running_state=True,
        )
        if checklist_requirements is not None and len(checklist_requirements.steps) >= 3:
            self.session_manager.sync_checklist(self.session, checklist_requirements)
        prompt_context = self.session_manager.build_prompt(
            self.session,
            self._system_prompt_for(self.agent_profile),
        )
        try:
            result = self.loop.run_result(
                messages=prompt_context.messages,
                system_prompt=prompt_context.system_prompt,
                estimated_tokens=prompt_context.estimated_tokens,
                stream_handler=stream_handler,
            )
            result = self._continue_multistep_if_needed(
                user_text=user_text,
                prompt_messages=prompt_context.messages,
                system_prompt=prompt_context.system_prompt,
                estimated_tokens=prompt_context.estimated_tokens,
                result=result,
                stream_handler=stream_handler,
            )
            if self._request_requires_tool(user_text) and result.tool_call_count == 0:
                self._emit("runtime.tool_enforcement.retry", {"session_id": self.session.id})
                result = self.loop.run_result(
                    messages=prompt_context.messages,
                    system_prompt=prompt_context.system_prompt + "\n" + TOOL_ENFORCEMENT_SUFFIX,
                    estimated_tokens=prompt_context.estimated_tokens,
                    stream_handler=stream_handler,
                )
                if result.tool_call_count == 0:
                    result = self._replace_unverified_result(
                        result,
                        "The request appears to require tools, but no tool was used. "
                        "I cannot verify that the requested workspace action actually happened.",
                    )
            history = result.history
            new_messages = history[len(prompt_context.messages):]
            self._refresh_session()
            self.session_manager.append_turn_messages(self.session, new_messages)
            if checklist_requirements is not None and len(checklist_requirements.steps) >= 3:
                self.session_manager.sync_checklist_progress(self.session, checklist_requirements)
            self.session.metadata["last_finish_reason"] = result.finish_reason
            self.session.metadata["last_loop_unstable"] = "true" if result.unstable else "false"
            self.session.metadata["last_loop_steps"] = str(result.step_count)
            self.session.metadata["last_loop_tool_calls"] = str(result.tool_call_count)
            self.session.metadata["last_prompt_notes"] = "|".join(prompt_context.notes)
            last_assistant = next(
                (message.content for message in reversed(self.session.messages) if message.role == "assistant"),
                "",
            )
            self.session.touch()
            self.session_manager.store.save(self.session)
            self._emit("loop.completed", {"session_id": self.session.id, "assistant_length": len(last_assistant)})
            logger.info("Completed turn for session %s", self.session.id)
            return last_assistant
        except Exception as exc:
            self._refresh_session()
            self.session_manager.fail_turn(self.session, str(exc))
            self._emit("loop.failed", {"session_id": self.session.id, "error": str(exc)})
            raise

    @property
    def session_id(self) -> str:
        return self.session.id

    def status_report(self) -> str:
        self._refresh_session()
        payload = {
            "session_id": self.session.id,
            "title": self.session.title,
            "active_agent": self.agent_profile.name,
            "yolo_mode": self.session.metadata.get("yolo_mode", "true" if self.settings.yolo_mode else "false"),
            "snapshot_enabled": self.session.metadata.get("snapshot_enabled", "true" if self.settings.snapshot_enabled else "false"),
            **status_payload(self.session),
            "summary_present": self.session.summary is not None,
            "compacted_message_count": self.session.summary.compacted_message_count if self.session.summary else 0,
            "message_count": len(self.session.messages),
            "todo_count": len(self.session.todos),
            "prompt_token_estimate": self.session.metadata.get("prompt_token_estimate"),
            "compacted_token_estimate": self.session.metadata.get("compacted_token_estimate"),
            "compaction_mode": self.session.metadata.get("compaction_mode"),
            "last_prompt_notes": self.session.metadata.get("last_prompt_notes"),
            "last_finish_reason": self.session.metadata.get("last_finish_reason"),
            "last_loop_unstable": self.session.metadata.get("last_loop_unstable"),
            "last_loop_steps": self.session.metadata.get("last_loop_steps"),
            "last_loop_tool_calls": self.session.metadata.get("last_loop_tool_calls"),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def inspect_session(self, limit: int = 12) -> str:
        self._refresh_session()
        return format_session_inspect(self.session, limit=limit)

    def replay_session(self) -> str:
        self._refresh_session()
        return format_session_replay(self.session)

    def list_agents(self, include_hidden: bool = False) -> str:
        payload = [
            {
                "name": profile.name,
                "description": profile.description,
                "mode": profile.mode,
                "hidden": profile.hidden,
                "steps": profile.steps,
                "active": profile.name == self.agent_profile.name,
            }
            for profile in self.agent_registry.list(include_hidden=include_hidden)
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def show_agent(self, name: str) -> str:
        profile = self.agent_registry.get(name)
        payload = {
            "name": profile.name,
            "description": profile.description,
            "mode": profile.mode,
            "hidden": profile.hidden,
            "native": profile.native,
            "steps": profile.steps,
            "inherits_default_prompt": profile.inherits_default_prompt,
            "allowed_tools": sorted(profile.allowed_tools) if profile.allowed_tools is not None else None,
            "permission_rules": [rule.to_dict() for rule in profile.permission_rules],
            "prompt": profile.prompt,
        }
        if profile.model is not None:
            payload["model"] = {
                "provider_id": profile.model.provider_id,
                "model_id": profile.model.model_id,
            }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def switch_agent(self, name: str) -> str:
        profile = self.agent_registry.get(name)
        if not profile.supports_primary():
            return f"Agent `{name}` is not a visible primary agent."
        self.agent_profile = profile
        self.session.metadata["active_agent"] = profile.name
        self.session.touch()
        self.session_manager.store.save(self.session)
        self.provider = self.provider_factory(profile)
        self.registry = self._build_registry_for_profile(profile)
        self.loop = AgentLoop(
            provider=self.provider,
            tool_registry=self.registry,
            tool_context=ToolContext(
                workspace=self.workspace,
                session_id=self.session.id,
                agent_name=profile.name,
                event_bus=self.event_bus,
                runtime_state=self._tool_runtime_state(profile.name),
                permission=dict(self.session.permission),
            ),
            event_bus=self.event_bus,
        )
        return f"Switched active agent to `{profile.name}`."

    def create_agent(self, description: str) -> str:
        prompt = f'Create an agent configuration based on this request: "{description}"'
        generated = self._hidden_generate_text("generate", prompt)
        if not generated:
            raise RuntimeError("generate agent returned no content")
        payload = self._parse_generated_agent_payload(generated)
        existing = {profile.name for profile in self.agent_registry.list(include_hidden=True)}
        profile = build_safe_profile_from_generated(
            payload,
            existing_names=existing,
            description_seed=description,
        )
        self.agent_store.save(profile)
        self.agent_registry = build_agent_registry(self.settings, store=self.agent_store)
        return f"Created agent `{profile.name}`."

    def conversation_summary(self) -> str:
        self._refresh_session()
        return self._generate_pr_summary(self.session.messages)

    def compact_session(self) -> str:
        changed = self.session_manager.compact(self.session)
        if not changed:
            return "Compaction not needed."
        return (
            f"Compacted session. Summary now covers "
            f"{self.session.summary.compacted_message_count if self.session.summary else 0} messages."
        )

    def revert_last_turn(self) -> str:
        changed = self.session_manager.revert_last_turn(self.session)
        return "Reverted last turn." if changed else "No turn to revert."

    def list_skills(self) -> str:
        policy = SessionPermissionPolicy(
            self.session_manager.store,
            self.agent_profile,
            yolo=self.session.permission.get("yolo", self.settings.yolo_mode),
            event_bus=self.event_bus,
        )
        result = self.skill_manager.discover()
        allowed = [skill for skill in result.skills if policy.allows_skill(self.session.id, skill.name)]
        payload = {
            "skills": [skill.to_dict() for skill in allowed],
            "denied": [skill.name for skill in result.skills if skill not in allowed],
            "errors": [error.to_dict() for error in result.errors],
            "roots": result.roots,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def load_skill(self, name: str) -> str:
        context = self.loop.tool_context.child(metadata={"tool_name": "skill"})
        result = self.registry.invoke("skill", {"name": name}, context)
        return result.content

    def mcp_status_report(self) -> str:
        if self.mcp_manager is None:
            return json.dumps({"enabled": False, "servers": []}, ensure_ascii=False, indent=2)
        payload = {"enabled": True, "servers": [state.to_dict() for state in self.mcp_manager.list_states()]}
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def mcp_tools_report(self) -> str:
        if self.mcp_manager is None:
            return json.dumps({"enabled": False, "tools": []}, ensure_ascii=False, indent=2)
        payload = {"enabled": True, "tools": [tool.to_dict() for tool in self.mcp_manager.list_tools()]}
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def mcp_resources_report(self) -> str:
        if self.mcp_manager is None:
            return json.dumps({"enabled": False, "resources": {}}, ensure_ascii=False, indent=2)
        return json.dumps({"enabled": True, "resources": self.mcp_manager.list_resources()}, ensure_ascii=False, indent=2)

    def mcp_prompts_report(self) -> str:
        if self.mcp_manager is None:
            return json.dumps({"enabled": False, "prompts": {}}, ensure_ascii=False, indent=2)
        return json.dumps({"enabled": True, "prompts": self.mcp_manager.list_prompts()}, ensure_ascii=False, indent=2)

    def mcp_inspect(self, server: str) -> str:
        if self.mcp_manager is None:
            return json.dumps({"enabled": False}, ensure_ascii=False, indent=2)
        return json.dumps(self.mcp_manager.inspect(server), ensure_ascii=False, indent=2)

    def mcp_reconnect(self, server: str) -> str:
        if self.mcp_manager is None:
            return "MCP is disabled."
        state = self.mcp_manager.reconnect(server)
        self._reload_runtime_registry()
        return json.dumps(state.to_dict(), ensure_ascii=False, indent=2)

    def mcp_ping(self, server: str) -> str:
        if self.mcp_manager is None:
            return json.dumps({"enabled": False}, ensure_ascii=False, indent=2)
        return json.dumps(self.mcp_manager.ping(server), ensure_ascii=False, indent=2)

    def mcp_auth(self, server: str, payload: dict[str, Any] | None = None) -> str:
        if self.mcp_manager is None:
            return json.dumps({"enabled": False}, ensure_ascii=False, indent=2)
        result = self.mcp_manager.set_auth(server, payload)
        self._reload_runtime_registry()
        return json.dumps(result, ensure_ascii=False, indent=2)

    def mcp_trace_report(self) -> str:
        if self.mcp_manager is None:
            return json.dumps({"enabled": False}, ensure_ascii=False, indent=2)
        return json.dumps(self.mcp_manager.trace(), ensure_ascii=False, indent=2)

    def mcp_call(self, server: str, tool: str, arguments: dict[str, Any]) -> str:
        if self.mcp_manager is None:
            return "MCP is disabled."
        tool_id = f"mcp__{self._safe_mcp_name(server)}__{self._safe_mcp_name(tool)}"
        if tool_id not in self.registry.ids(self.loop.tool_context):
            self._reload_runtime_registry()
        context = self.loop.tool_context.child(metadata={"tool_name": tool_id})
        return self.registry.invoke(tool_id, arguments, context).content

    def mcp_read_resource(self, server: str, uri: str) -> str:
        if self.mcp_manager is None:
            return "MCP is disabled."
        context = self.loop.tool_context.child(metadata={"tool_name": "mcp_read_resource"})
        return self.registry.invoke("mcp_read_resource", {"server": server, "uri": uri}, context).content

    def mcp_get_prompt(self, server: str, name: str, arguments: dict[str, Any]) -> str:
        if self.mcp_manager is None:
            return "MCP is disabled."
        context = self.loop.tool_context.child(metadata={"tool_name": "mcp_get_prompt"})
        return self.registry.invoke(
            "mcp_get_prompt",
            {"server": server, "name": name, "arguments": arguments},
            context,
        ).content

    def retry_last_turn(self) -> str:
        last_user_message = self.session_manager.retry_last_turn(self.session)
        if not last_user_message:
            return "No previous user message to retry."
        self.session_manager.revert_last_turn(self.session)
        time.sleep(self.session_manager.retry_delay_ms(self.session) / 1000)
        return self.run_turn(last_user_message)

    def list_snapshots(self) -> str:
        self._refresh_session()
        snapshots = self.snapshot_manager.list_snapshots(self.session.id)
        payload = [
            {
                "id": item.id,
                "snapshot_hash": item.snapshot_hash,
                "tool_name": item.tool_name,
                "tool_call_id": item.tool_call_id,
                "task_id": item.task_id,
                "status": item.status,
                "changed_files": item.changed_files,
                "created_at": item.created_at,
                "reverted_at": item.reverted_at,
            }
            for item in snapshots
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def rollback(self, scope: str, target: str | None = None, file_path: str | None = None) -> str:
        self._refresh_session()
        if not self.settings.snapshot_enabled:
            return "Snapshot is disabled."
        files = [file_path] if file_path else None
        if scope == "last":
            snapshots = self.snapshot_manager.list_snapshots(self.session.id)
            if not snapshots:
                return "No snapshot available."
            candidate = next(
                (
                    item
                    for item in snapshots
                    if item.status != "reverted"
                    and item.changed_files
                    and (not file_path or file_path in item.changed_files)
                ),
                None,
            )
            if candidate is None:
                return "No revertible snapshot available."
            result = self.snapshot_manager.revert_snapshot(candidate.id, files=files)
        elif scope == "snapshot" and target:
            result = self.snapshot_manager.revert_snapshot(target, files=files)
        elif scope == "tool" and target:
            result = self.snapshot_manager.revert_tool_call(self.session.id, target, files=files)
        elif scope == "task" and target:
            result = self.snapshot_manager.revert_task(self.session.id, target, files=files)
        elif scope == "file" and target:
            result = self.snapshot_manager.revert_file(self.session.id, target)
        else:
            return "Usage: /rollback last [file] | /rollback snapshot <id> [file] | /rollback tool <tool_call_id> [file] | /rollback task <task_id> [file] | /rollback file <path>"
        self._refresh_session()
        self.session.messages.append(build_snapshot_revert_message(result))
        self.session.touch()
        self.session_manager.store.save(self.session)
        return f"Reverted {len(result.reverted_files)} file(s): " + ", ".join(result.reverted_files)

    def add_todo(self, content: str, priority: str = "medium") -> str:
        self.session_manager.add_todo(self.session, content, priority)
        return f"Added todo: {content}"

    def complete_todo(self, index: int) -> str:
        self.session_manager.complete_todo(self.session, index)
        return f"Completed todo #{index + 1}"

    def clear_todos(self) -> str:
        self.session_manager.clear_todos(self.session)
        return "Cleared todos."

    def set_question_handler(self, handler: Callable[[list[dict[str, Any]]], list[str]] | None) -> None:
        self.question_handler = handler
        self.loop.tool_context.runtime_state = self._tool_runtime_state(self.agent_profile.name)

    def set_permission_handler(self, handler: Callable[[Any], str] | None) -> None:
        self.permission_handler = handler
        self.loop.tool_context.runtime_state = self._tool_runtime_state(self.agent_profile.name)

    def set_yolo_mode(self, enabled: bool) -> str:
        self.settings.yolo_mode = enabled
        policy = getattr(self.registry, "_permission_policy", None)
        if isinstance(policy, SessionPermissionPolicy):
            policy.set_yolo(self.session.id, enabled)
        else:
            self.session.permission["yolo"] = enabled
            self.session.metadata["yolo_mode"] = "true" if enabled else "false"
            self.session.touch()
            self.session_manager.store.save(self.session)
        self._refresh_session()
        return f"YOLO mode {'enabled' if enabled else 'disabled'}."

    def _build_subagent_manager(self) -> SubagentManager:
        return SubagentManager(
            provider_factory=self.provider_factory,
            registry_factory=self._build_subagent_registry,
            workspace=self.workspace,
            prompt_factory=self._system_prompt_for_agent_name,
            profile_lookup=self.agent_registry.get,
            event_bus=self.event_bus,
            session_id_factory=lambda: self.session.id,
            runtime_state_factory=self._tool_runtime_state,
        )

    def _reload_runtime_registry(self) -> None:
        self.registry = self._build_registry_for_profile(self.agent_profile)
        self.loop = AgentLoop(
            provider=self.provider,
            tool_registry=self.registry,
            tool_context=ToolContext(
                workspace=self.workspace,
                session_id=self.session.id,
                agent_name=self.agent_profile.name,
                event_bus=self.event_bus,
                runtime_state=self._tool_runtime_state(self.agent_profile.name),
                permission=dict(self.session.permission),
            ),
            event_bus=self.event_bus,
        )

    def _build_registry(self, profile: AgentProfile | None = None) -> ToolRegistry:
        active_profile = profile or self.agent_profile
        policy = SessionPermissionPolicy(
            self.session_manager.store,
            active_profile,
            yolo=self.session.permission.get("yolo", self.settings.yolo_mode),
            event_bus=self.event_bus,
        )
        registry = ToolRegistry(permission_policy=policy, snapshot_manager=self.snapshot_manager)
        registry.register(ReadFileTool())
        registry.register(ReadFileRangeTool())
        registry.register(ReadTool())
        registry.register(BackgroundTaskTool(self.background_tasks))
        registry.register(EnsureDirTool())
        registry.register(WriteFileTool())
        registry.register(WriteTool())
        registry.register(AppendFileTool())
        registry.register(EditFileTool())
        registry.register(ReplaceAllTool())
        registry.register(InsertTextTool())
        registry.register(EditTool())
        registry.register(MultiEditTool())
        registry.register(ApplyPatchTool())
        registry.register(PatchTool())
        registry.register(ListFilesTool())
        registry.register(LsTool())
        registry.register(GlobTool())
        registry.register(GrepTool())
        registry.register(CodeSearchTool())
        registry.register(ReadSymbolTool())
        registry.register(WebFetchTool())
        registry.register(WebSearchTool())
        registry.register(QuestionTool())
        registry.register(SkillTool())
        registry.register(LspTool())
        registry.register(BatchTool())
        registry.register(TodoWriteTool())
        registry.register(TodoReadTool())
        registry.register(BashTool(timeout_seconds=self.settings.bash_timeout_seconds))
        registry.register(DelegateTool(self.subagent_manager))
        registry.register(TaskTool(self.subagent_manager))
        if self.mcp_manager is not None:
            self.mcp_manager.connect_all()
            registry.register(McpReadResourceTool(self.mcp_manager))
            registry.register(McpGetPromptTool(self.mcp_manager))
            for info in self.mcp_manager.list_tools():
                registry.register(McpTool(self.mcp_manager, info))
        return registry

    def _build_registry_for_profile(self, profile: AgentProfile) -> ToolRegistry:
        registry = self._build_registry(profile)
        if profile.allowed_tools is None:
            return registry
        policy = SessionPermissionPolicy(
            self.session_manager.store,
            profile,
            yolo=self.session.permission.get("yolo", self.settings.yolo_mode),
            event_bus=self.event_bus,
        )
        filtered = ToolRegistry(permission_policy=policy, snapshot_manager=self.snapshot_manager)
        for name in profile.allowed_tools:
            try:
                filtered.register(registry.get(name))
            except KeyError:
                continue
        return filtered

    def _build_subagent_registry(self, agent_name: str) -> ToolRegistry:
        profile = self.agent_registry.get(agent_name)
        return self._build_registry_for_profile(profile)

    def _tool_runtime_state(self, agent_name: str) -> dict[str, Any]:
        permission_handler = self.permission_handler or (lambda _request: "once")
        return {
            "mode": "runtime",
            "session": self.session,
            "background_tasks": self.background_tasks,
            "get_todos": lambda: list(self.session.todos),
            "set_todos": self._set_todos,
            "invoke_tool": self._invoke_tool_from_runtime,
            "question_handler_available": str(self.question_handler is not None).lower(),
            "ask_questions": self.question_handler,
            "ask_permission": permission_handler,
            "skill_roots": self._skill_roots(),
            "skill_manager": self.skill_manager,
            "skill_allowed": self._skill_allowed_for_agent(agent_name),
            "lsp_manager": self.lsp_manager,
            "mcp_manager": self.mcp_manager,
            "agent_name": agent_name,
            "active_agent": self.agent_profile.name,
            "agent_registry": self.agent_registry,
            "yolo_mode": self.session.metadata.get("yolo_mode", "true" if self.settings.yolo_mode else "false"),
            "permission_state": self.session.permission,
        }

    def _refresh_session(self) -> None:
        self.session = self.session_manager.store.load(self.session.id)
        self.session.permission.setdefault("rules", [])
        self.session.permission.setdefault("yolo", self.settings.yolo_mode)
        self.loop.tool_context.session_id = self.session.id
        active_name = self.session.metadata.get("active_agent") or self.agent_profile.name
        self.agent_profile = self.agent_registry.get(active_name)
        self.loop.tool_context.agent_name = self.agent_profile.name
        self.loop.tool_context.runtime_state = self._tool_runtime_state(self.agent_profile.name)
        self.loop.tool_context.permission = dict(self.session.permission)

    def _set_todos(self, todos: list) -> None:
        normalized_manual = []
        for todo in todos:
            todo.status = self._normalize_todo_status(getattr(todo, "status", "pending"))
            normalized_manual.append(todo)
        existing_auto = [todo for todo in self.session.todos if todo.source == "auto-checklist"]
        if existing_auto and self._looks_like_checklist_status_update(normalized_manual, existing_auto):
            for existing, incoming in zip(existing_auto, normalized_manual):
                existing.status = incoming.status
                if incoming.priority:
                    existing.priority = incoming.priority
            self.session.todos = [todo for todo in self.session.todos if todo.source != "auto-checklist"] + existing_auto
        else:
            self.session.todos = [todo for todo in self.session.todos if todo.source == "auto-checklist"] + normalized_manual
        self.session.touch()
        self.session_manager.store.save(self.session)

    @staticmethod
    def _looks_like_checklist_status_update(incoming: list, existing_auto: list) -> bool:
        if len(incoming) != len(existing_auto):
            return False
        if len(incoming) >= 3:
            return True
        for auto_todo, manual_todo in zip(existing_auto, incoming):
            auto_text = AgentRuntime._normalize_todo_text(auto_todo.content)
            manual_text = AgentRuntime._normalize_todo_text(manual_todo.content)
            if not auto_text or not manual_text:
                return False
            if auto_text == manual_text:
                continue
            if auto_text in manual_text or manual_text in auto_text:
                continue
            return False
        return True

    @staticmethod
    def _normalize_todo_text(text: str) -> str:
        normalized = (text or "").strip()
        if normalized.startswith("[") and "]" in normalized:
            normalized = normalized.split("]", 1)[1].strip()
        normalized = normalized.replace("`", "")
        return " ".join(normalized.split()).lower()

    @staticmethod
    def _normalize_todo_status(status: str) -> str:
        normalized = (status or "pending").strip().lower()
        if normalized in {"completed", "complete", "done", "finished"}:
            return "completed"
        return "pending"

    def _invoke_tool_from_runtime(self, tool_name: str, arguments: dict[str, Any], parent_context: ToolContext | None = None):
        agent_name = parent_context.agent_name if parent_context else self.agent_profile.name
        context = ToolContext(
            workspace=self.workspace,
            session_id=self.session.id,
            message_id=parent_context.message_id if parent_context else None,
            tool_call_id=parent_context.tool_call_id if parent_context else None,
            agent_name=agent_name,
            event_bus=self.event_bus,
            runtime_state=self._tool_runtime_state(agent_name),
            permission=dict(self.session.permission),
        )
        if parent_context and parent_context.metadata:
            context.metadata.update(parent_context.metadata)
        return self.registry.invoke(tool_name, arguments, context)

    def _system_prompt_for(self, profile: AgentProfile) -> str:
        prompt = compose_agent_prompt(profile)
        skills = self._skill_prompt_for(profile)
        if skills:
            prompt = prompt + "\n\n" + skills
        return build_system_prompt(self.session, prompt)

    def _system_prompt_for_agent_name(self, agent_name: str) -> str:
        profile = self.agent_registry.get(agent_name)
        return self._system_prompt_for(profile)

    def _hidden_generate_text(
        self,
        agent_name: str,
        user_text: str,
        *,
        session: Session | None = None,
    ) -> str | None:
        if not self.hidden_agents_enabled:
            return None
        profile = self.agent_registry.get(agent_name)
        provider = self.provider_factory(profile)
        target_session = session or self.session
        response = provider.generate(
            messages=[Message(role="user", content=user_text)],
            tools=[],
            system_prompt=build_system_prompt(target_session, compose_agent_prompt(profile)),
        )
        text = response.text.strip()
        return text or None

    def _generate_session_title(self, session: Session, user_text: str) -> str | None:
        try:
            title = self._hidden_generate_text("title", user_text, session=session)
            if title:
                return title.splitlines()[0].strip()[:50]
        except Exception:
            return None
        return None

    def _generate_compaction_summary(self, session: Session, messages: list[Message]) -> str | None:
        if not messages:
            return None
        fallback = summarize_messages(messages)
        prompt = (
            "Summarize the following conversation context for continuation.\n\n"
            + "\n\n".join(f"[{message.role}] {message.content}" for message in messages[-24:])
        )
        try:
            summary = self._hidden_generate_text("compaction", prompt, session=session)
            return summary or fallback
        except Exception:
            return fallback

    def _generate_pr_summary(self, messages: list[Message]) -> str:
        fallback = summarize_messages(messages)
        prompt = "\n\n".join(f"[{message.role}] {message.content}" for message in messages[-32:])
        try:
            summary = self._hidden_generate_text("summary", prompt)
            if summary and summary.strip().lower() != "ok":
                return summary
            return fallback
        except Exception:
            return fallback

    @staticmethod
    def _parse_generated_agent_payload(text: str) -> GeneratedAgentPayload:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json\n", "", 1)
        payload = json.loads(cleaned)
        required = {"identifier", "whenToUse", "systemPrompt"}
        missing = required - payload.keys()
        if missing:
            raise RuntimeError(f"generated agent payload missing fields: {sorted(missing)}")
        return GeneratedAgentPayload(
            identifier=str(payload["identifier"]).strip(),
            when_to_use=str(payload["whenToUse"]).strip(),
            system_prompt=str(payload["systemPrompt"]).strip(),
        )

    def _auto_switch_agent(self, decision: RoutingDecision) -> None:
        source = self.agent_profile.name
        target = decision.target_agent or source
        self.switch_agent(target)
        self.session_manager.append_message(
            self.session,
            Message(
                role="assistant",
                agent="session-op",
                content=f"[Agent Handoff] {source} -> {target} ({decision.reason})",
                finish="stop",
                parts=[
                    Part(
                        type="agent",
                        content={
                            "action": "switch",
                            "source_agent": source,
                            "target_agent": target,
                            "reason": decision.reason,
                        },
                        state={"status": "completed"},
                    )
                ],
            ),
        )

    def _auto_delegate_turn(self, user_text: str, decision: RoutingDecision) -> str:
        self._refresh_session()
        self._emit("message.added", {"role": "user", "session_id": self.session.id})
        self.session_manager.append_message(
            self.session,
            Message(role="user", content=user_text),
            mark_running_state=True,
        )
        target = decision.target_agent or "explore"
        result = self.subagent_manager.run(user_text, agent_name=target)
        handoff = Message(
            role="assistant",
            agent="session-op",
            content=f"[Agent Handoff] {self.agent_profile.name} -> {target} ({decision.reason})",
            finish="stop",
            parts=[
                Part(
                    type="agent",
                    content={
                        "action": "delegate",
                        "source_agent": self.agent_profile.name,
                        "target_agent": target,
                        "reason": decision.reason,
                        "status": "completed",
                    },
                    state={"status": "completed"},
                )
            ],
        )
        reply = Message(
            role="assistant",
            agent=target,
            content=result.summary,
            finish="stop",
            parts=[
                Part(
                    type="subtask",
                    content={
                        "agent": result.agent_name,
                        "summary": result.summary,
                        "touched_paths": result.touched_paths,
                        "verified_paths": result.verified_paths,
                    },
                    state={"status": "completed"},
                ),
                Part(
                    type="agent",
                    content={
                        "action": "return",
                        "source_agent": target,
                        "target_agent": self.agent_profile.name,
                        "reason": "delegated-result",
                    },
                    state={"status": "completed"},
                ),
                Part(type="text", content=result.summary),
            ],
        )
        self._refresh_session()
        self.session_manager.append_turn_messages(self.session, [handoff, reply])
        self.session.metadata["last_finish_reason"] = "stop"
        self.session.metadata["last_loop_unstable"] = "false"
        self.session.metadata["last_loop_steps"] = "0"
        self.session.metadata["last_loop_tool_calls"] = "0"
        self.session.metadata["last_prompt_notes"] = "auto-delegate"
        self.session.touch()
        self.session_manager.store.save(self.session)
        self._emit(
            "agent.auto_delegate",
            {
                "session_id": self.session.id,
                "source_agent": self.agent_profile.name,
                "target_agent": target,
                "reason": decision.reason,
            },
        )
        return result.summary

    @staticmethod
    def _skill_roots() -> list[str]:
        roots = ["/root/.codex/skills", str((Path.cwd() / ".codex" / "skills").resolve())]
        seen: list[str] = []
        for root in roots:
            if root not in seen:
                seen.append(root)
        return seen

    @staticmethod
    def _safe_mcp_name(value: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value.strip())
        safe = "_".join(part for part in safe.split("_") if part)
        return safe or "unnamed"

    def _skill_prompt_for(self, profile: AgentProfile) -> str:
        try:
            policy = SessionPermissionPolicy(
                self.session_manager.store,
                profile,
                yolo=self.session.permission.get("yolo", self.settings.yolo_mode),
                event_bus=self.event_bus,
            )
            result = self.skill_manager.discover()
            available = [skill for skill in result.skills if policy.allows_skill(self.session.id, skill.name)]
            if not available:
                return ""
            return "\n".join(
                [
                    "Skills provide specialized instructions and workflows for specific tasks.",
                    "Decide yourself whether the current task should use a skill. If a listed skill matches the task, call the unified `skill` tool with that skill name before following its workflow.",
                    "Do not load a skill just because it is listed. If no skill clearly matches, continue without using one.",
                    "Only the name and description are shown here; the full skill body is loaded lazily by the `skill` tool.",
                    "Do not use read_file, grep, or other filesystem tools to load a SKILL.md as a substitute for the `skill` tool. Direct file reads are for inspecting project files, not activating a skill.",
                    "If the user explicitly asks you to decide whether a skill is relevant, make that decision from the descriptions below and call `skill` when one directly applies.",
                    self.skill_manager.format_available(verbose=True, skills=available),
                ]
            )
        except Exception:
            return ""

    def _skill_allowed_for_agent(self, agent_name: str):
        profile = self.agent_registry.get(agent_name)

        def allowed(skill_name: str) -> bool:
            policy = SessionPermissionPolicy(
                self.session_manager.store,
                profile,
                yolo=self.session.permission.get("yolo", self.settings.yolo_mode),
                event_bus=self.event_bus,
            )
            return policy.allows_skill(self.session.id, skill_name)

        return allowed

    def _emit(self, event_type: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        self.event_bus.emit(Event(type=event_type, payload=payload))

    @staticmethod
    def _request_requires_tool(user_text: str) -> bool:
        lowered = user_text.lower()
        planning_only_tokens = [
            "不要修改代码",
            "不要修改",
            "只说明",
            "只分析",
            "仅分析",
            "只给方案",
            "先分析",
            "只返回函数名",
            "不需要执行",
        ]
        if any(token in lowered for token in planning_only_tokens):
            direct_tool_targets = [
                "读取",
                "查找",
                "搜索",
                "定位",
                "运行测试",
                "执行命令",
                "read ",
                "grep",
                "glob",
                "search",
                "find ",
            ]
            if not any(token in lowered for token in direct_tool_targets):
                return False
        keywords = [
            "read ",
            "write ",
            "edit ",
            "append ",
            "list ",
            "bash",
            "command",
            "file",
            "directory",
            "workspace",
            "读取",
            "创建",
            "写入",
            "修改",
            "编辑",
            "追加",
            "列出",
            "执行",
            "文件",
            "目录",
            "工作区",
        ]
        return any(keyword in lowered for keyword in keywords)

    @staticmethod
    def _replace_unverified_result(result, message: str):
        history = list(result.history)
        if history and history[-1].role == "assistant":
            history[-1].content = message
            history[-1].finish = "other"
        else:
            history.append(Message(role="assistant", content=message, finish="other"))
        result.history = history
        result.finish_reason = "other"
        return result

    def _continue_multistep_if_needed(
        self,
        user_text: str,
        prompt_messages: list[Message],
        system_prompt: str,
        estimated_tokens: int,
        result,
        stream_handler: Callable[[dict[str, Any]], None] | None,
    ):
        if not looks_multistep(user_text):
            return result
        requirements = parse_multistep_requirements(user_text)
        max_rounds = 4
        current = result
        for _ in range(max_rounds):
            final_reply = next((m.content for m in reversed(current.history) if m.role == "assistant"), "")
            validation = validate_multistep_requirements(self.workspace, requirements, final_reply=final_reply)
            if validation.complete:
                return current
            self._emit(
                "runtime.multistep.continue",
                {"session_id": self.session.id, "missing": validation.missing},
            )
            continuation_prompt = (
                system_prompt
                + "\n"
                + MULTISTEP_CONTINUATION_SUFFIX
                + "\nUnfinished requirements:\n- "
                + "\n- ".join(validation.missing)
            )
            current = self.loop.run_result(
                messages=current.history,
                system_prompt=continuation_prompt,
                estimated_tokens=estimated_tokens,
                stream_handler=stream_handler,
            )
        final_reply = next((m.content for m in reversed(current.history) if m.role == "assistant"), "")
        validation = validate_multistep_requirements(self.workspace, requirements, final_reply=final_reply)
        if not validation.complete:
            current = self._replace_unverified_result(
                current,
                "多步任务未完全完成，仍有未满足项：\n- " + "\n- ".join(validation.missing),
            )
        return current


def build_default_runtime(
    workspace: str | Path = ".",
    session_id: str | None = None,
    session_root: str | Path | None = None,
    agent_name: str | None = None,
    yolo: bool | None = None,
) -> AgentRuntime:
    settings = Settings.from_workspace(workspace)
    explicit_yolo = yolo is not None
    if yolo is not None:
        settings.yolo_mode = yolo
    workspace_path = settings.workspace
    manager = build_session_manager(workspace=workspace_path, session_root=session_root or settings.session_root)
    session = manager.start(workspace=workspace_path, session_id=session_id)
    if explicit_yolo or settings.yolo_mode:
        session.permission["yolo"] = settings.yolo_mode
        session.metadata["yolo_mode"] = "true" if settings.yolo_mode else "false"
        session.touch()
        manager.store.save(session)
    event_bus = EventBus(settings.log_root / f"{session.id}.jsonl")
    agent_store = AgentStore(settings.agent_root)
    agent_registry = build_agent_registry(settings, store=agent_store)

    def provider_factory(profile: AgentProfile | str | None = None) -> BaseProvider:
        if isinstance(profile, str):
            profile = agent_registry.get(profile)
        return build_provider(settings, model_override=profile.model if profile else None)

    active_profile = agent_registry.get(
        agent_name
        or session.metadata.get("active_agent")
        or agent_registry.default_primary().name
    )
    provider = provider_factory(active_profile)
    return AgentRuntime(
        provider=provider,
        workspace=workspace_path,
        session_manager=manager,
        session=session,
        settings=settings,
        event_bus=event_bus,
        provider_factory=provider_factory,
        agent_registry=agent_registry,
        agent_name=active_profile.name,
    )


def build_session_manager(
    workspace: str | Path = ".",
    session_root: str | Path | None = None,
) -> SessionManager:
    settings = Settings.from_workspace(workspace)
    store = SessionStore(Path(session_root) if session_root else settings.session_root)
    return SessionManager(
        store,
        max_messages_before_compact=settings.compact_max_messages,
        prompt_recent_messages=settings.prompt_recent_messages,
        prompt_max_tokens=settings.prompt_max_tokens,
    )
