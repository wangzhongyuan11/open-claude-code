from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from openagent.domain.messages import ModelRef
from openagent.permission.models import PermissionRule


AgentMode = Literal["primary", "subagent", "all"]


@dataclass(slots=True)
class AgentProfile:
    name: str
    description: str = ""
    mode: AgentMode = "primary"
    native: bool = True
    hidden: bool = False
    prompt: str | None = None
    model: ModelRef | None = None
    variant: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    color: str | None = None
    steps: int | None = None
    inherits_default_prompt: bool = True
    allowed_tools: set[str] | None = None
    permission_rules: list[PermissionRule] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def supports_primary(self) -> bool:
        return self.mode in {"primary", "all"} and not self.hidden

    def supports_subagent(self) -> bool:
        return self.mode in {"subagent", "all"} and not self.hidden

    def visible(self) -> bool:
        return not self.hidden
