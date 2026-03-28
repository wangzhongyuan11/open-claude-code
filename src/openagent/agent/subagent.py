from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from openagent.agent.loop import AgentLoop
from openagent.agent.profile import AgentProfile
from openagent.domain.events import Event
from openagent.domain.messages import Message
from openagent.domain.tools import ToolContext
from openagent.events.bus import EventBus
from openagent.providers.base import BaseProvider
from openagent.tools.registry import ToolRegistry

ProviderFactory = Callable[[str | None], BaseProvider]
RegistryFactory = Callable[[str], ToolRegistry]
PromptFactory = Callable[[str], str]
ProfileLookup = Callable[[str], AgentProfile]


@dataclass(slots=True)
class SubagentResult:
    summary: str
    history: list[Message]
    touched_paths: list[str]
    verified_paths: list[str]


class SubagentManager:
    def __init__(
        self,
        provider_factory: ProviderFactory,
        registry_factory: RegistryFactory,
        workspace: Path,
        prompt_factory: PromptFactory | None = None,
        profile_lookup: ProfileLookup | None = None,
        system_prompt: str | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.provider_factory = provider_factory
        self.registry_factory = registry_factory
        self.workspace = workspace.resolve()
        self.prompt_factory = prompt_factory or (lambda _agent: system_prompt or "You are a focused coding subagent.")
        self.profile_lookup = profile_lookup or (
            lambda agent_name: AgentProfile(name=agent_name, mode="subagent", prompt=None, steps=8)
        )
        self.event_bus = event_bus

    def run(self, prompt: str, agent_name: str = "general", max_steps: int | None = None) -> SubagentResult:
        profile = self.profile_lookup(agent_name)
        if self.event_bus:
            self.event_bus.emit(Event(type="subagent.started", payload={"prompt": prompt, "agent": profile.name}))
        try:
            provider = self.provider_factory(profile.name)
        except TypeError:
            provider = self.provider_factory()  # type: ignore[misc]
        try:
            registry = self.registry_factory(profile.name)
        except TypeError:
            registry = self.registry_factory()  # type: ignore[misc]
        loop = AgentLoop(
            provider=provider,
            tool_registry=registry,
            tool_context=ToolContext(
                workspace=self.workspace,
                session_id="subagent",
                agent_name=profile.name,
                event_bus=self.event_bus,
                metadata={"agent": profile.name},
            ),
            event_bus=self.event_bus,
        )
        history = loop.run(
            messages=[Message(role="user", content=prompt)],
            system_prompt=self.prompt_factory(profile.name),
            max_steps=max_steps or profile.steps or 8,
        )
        summary = next(
            (message.content for message in reversed(history) if message.role == "assistant" and message.content),
            "",
        )
        touched_paths, verified_paths = self._collect_artifacts(history)
        if self.event_bus:
            self.event_bus.emit(
                Event(
                    type="subagent.completed",
                    payload={
                        "agent": profile.name,
                        "summary_length": len(summary),
                        "touched_paths": touched_paths,
                        "verified_paths": verified_paths,
                    },
                )
            )
        return SubagentResult(
            summary=summary,
            history=history,
            touched_paths=touched_paths,
            verified_paths=verified_paths,
        )

    @staticmethod
    def _collect_artifacts(history: list[Message]) -> tuple[list[str], list[str]]:
        touched_paths: list[str] = []
        verified_paths: list[str] = []
        tool_call_paths: dict[str, tuple[str, str]] = {}
        for message in history:
            if message.role == "assistant" and message.tool_calls:
                for tool_call in message.tool_calls:
                    path = tool_call.arguments.get("path")
                    if not path:
                        continue
                    tool_call_paths[tool_call.id] = (tool_call.name, str(path))
                    if tool_call.name in {"write_file", "append_file", "edit_file"}:
                        touched_paths.append(str(path))
            elif message.role == "tool" and message.tool_call_id in tool_call_paths:
                tool_name, path = tool_call_paths[message.tool_call_id]
                if tool_name == "read_file":
                    verified_paths.append(path)
        return sorted(set(touched_paths)), sorted(set(verified_paths))


def format_subagent_report(result: SubagentResult) -> str:
    payload = {
        "status": "completed",
        "summary": result.summary,
        "touched_paths": result.touched_paths,
        "verified_paths": result.verified_paths,
    }
    return "<delegate_result>\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n</delegate_result>"
