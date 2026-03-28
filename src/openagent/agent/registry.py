from __future__ import annotations

from dataclasses import replace

from openagent.agent.profile import AgentProfile
from openagent.agent.prompts import (
    PROMPT_COMPACTION,
    PROMPT_EXPLORE,
    PROMPT_GENERAL,
    PROMPT_PLAN,
    PROMPT_SUMMARY,
    PROMPT_TITLE,
)
from openagent.config.settings import Settings


class AgentRegistry:
    def __init__(self, profiles: dict[str, AgentProfile], default_agent: str = "build") -> None:
        self._profiles = dict(profiles)
        self._default_agent = default_agent

    def get(self, name: str) -> AgentProfile:
        try:
            return self._profiles[name]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {name}") from exc

    def list(self, include_hidden: bool = False) -> list[AgentProfile]:
        profiles = list(self._profiles.values())
        if not include_hidden:
            profiles = [profile for profile in profiles if not profile.hidden]
        return sorted(profiles, key=lambda item: (0 if item.name == self._default_agent else 1, item.name))

    def default_primary(self) -> AgentProfile:
        requested = self._profiles.get(self._default_agent)
        if requested and requested.supports_primary():
            return requested
        for profile in self.list(include_hidden=False):
            if profile.supports_primary():
                return profile
        raise RuntimeError("no visible primary agent configured")

    def visible_primary_names(self) -> list[str]:
        return [profile.name for profile in self.list(include_hidden=False) if profile.supports_primary()]

    def visible_subagent_names(self) -> list[str]:
        return [profile.name for profile in self.list(include_hidden=False) if profile.supports_subagent()]

    def hidden_names(self) -> list[str]:
        return [profile.name for profile in self.list(include_hidden=True) if profile.hidden]


def build_agent_registry(settings: Settings) -> AgentRegistry:
    readonly_tools = {
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
        "bash",
    }
    plan_tools = readonly_tools | {"todowrite"}

    profiles = {
        "build": AgentProfile(
            name="build",
            description="The default coding agent. Uses tools to inspect, modify, and verify the workspace.",
            mode="primary",
            steps=12,
        ),
        "plan": AgentProfile(
            name="plan",
            description="Planning mode. Reads the repository and produces implementation plans without editing files.",
            mode="primary",
            prompt=PROMPT_PLAN,
            allowed_tools=plan_tools,
            steps=10,
        ),
        "general": AgentProfile(
            name="general",
            description="General-purpose subagent for focused delegated coding tasks.",
            mode="subagent",
            prompt=PROMPT_GENERAL,
            steps=8,
        ),
        "explore": AgentProfile(
            name="explore",
            description="Fast subagent specialized for codebase exploration and file search.",
            mode="subagent",
            prompt=PROMPT_EXPLORE,
            allowed_tools=readonly_tools,
            steps=8,
        ),
        "compaction": AgentProfile(
            name="compaction",
            description="Hidden agent that summarizes older conversation context for continuation.",
            mode="primary",
            hidden=True,
            prompt=PROMPT_COMPACTION,
            inherits_default_prompt=False,
            allowed_tools=set(),
            steps=1,
        ),
        "summary": AgentProfile(
            name="summary",
            description="Hidden agent that produces a pull-request style summary of the conversation.",
            mode="primary",
            hidden=True,
            prompt=PROMPT_SUMMARY,
            inherits_default_prompt=False,
            allowed_tools=set(),
            steps=1,
        ),
        "title": AgentProfile(
            name="title",
            description="Hidden agent that produces a short conversation title.",
            mode="primary",
            hidden=True,
            prompt=PROMPT_TITLE,
            inherits_default_prompt=False,
            allowed_tools=set(),
            steps=1,
        ),
    }

    default_agent = settings.default_agent or "build"
    if default_agent not in profiles:
        default_agent = "build"

    # Reserve a hook for future user-defined agent overrides.
    for name, profile in list(profiles.items()):
        profiles[name] = replace(profile)
    return AgentRegistry(profiles=profiles, default_agent=default_agent)
