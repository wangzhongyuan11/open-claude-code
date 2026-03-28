from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    workspace: Path
    session_root: Path
    log_root: Path
    provider_name: str = "anthropic"
    model: str = "claude-3-7-sonnet-latest"
    default_agent: str = "build"
    base_url: str | None = None
    api_key: str | None = None
    bash_timeout_seconds: int = 30
    compact_max_messages: int = 20
    prompt_recent_messages: int = 12
    prompt_max_tokens: int = 12000

    @classmethod
    def from_workspace(cls, workspace: str | Path) -> "Settings":
        workspace_path = Path(workspace).resolve()
        state_root = workspace_path / ".openagent"
        provider_name = os.getenv("OPENAGENT_PROVIDER", "anthropic")
        model = os.getenv("OPENAGENT_MODEL", "claude-3-7-sonnet-latest")
        default_agent = os.getenv("OPENAGENT_DEFAULT_AGENT", "build")
        base_url = os.getenv("OPENAGENT_BASE_URL")
        api_key = None
        if provider_name == "volcengine":
            api_key = os.getenv("ARK_API_KEY") or os.getenv("VOLCENGINE_ARK_API_KEY")
            base_url = base_url or os.getenv("ARK_BASE_URL")
        elif provider_name == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
        bash_timeout_seconds = int(os.getenv("OPENAGENT_BASH_TIMEOUT", "30"))
        compact_max_messages = int(os.getenv("OPENAGENT_COMPACT_MAX_MESSAGES", "20"))
        prompt_recent_messages = int(os.getenv("OPENAGENT_PROMPT_RECENT_MESSAGES", "12"))
        prompt_max_tokens = int(os.getenv("OPENAGENT_PROMPT_MAX_TOKENS", "12000"))
        return cls(
            workspace=workspace_path,
            session_root=state_root / "sessions",
            log_root=state_root / "logs",
            provider_name=provider_name,
            model=model,
            default_agent=default_agent,
            base_url=base_url,
            api_key=api_key,
            bash_timeout_seconds=bash_timeout_seconds,
            compact_max_messages=compact_max_messages,
            prompt_recent_messages=prompt_recent_messages,
            prompt_max_tokens=prompt_max_tokens,
        )
