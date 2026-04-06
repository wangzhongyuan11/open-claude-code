from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SkillInfo:
    name: str
    description: str
    location: str
    source: str
    scope: str
    compatibility: list[str] = field(default_factory=list)
    license: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def base_dir(self) -> str:
        return str(Path(self.location).parent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "source": self.source,
            "scope": self.scope,
            "compatibility": self.compatibility,
            "license": self.license,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class LoadedSkill:
    info: SkillInfo
    content: str
    files: list[str]


@dataclass(slots=True)
class SkillLoadError:
    path: str
    type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "type": self.type, "message": self.message}

