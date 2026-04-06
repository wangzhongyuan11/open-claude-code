from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from openagent.skill.models import LoadedSkill, SkillInfo, SkillLoadError


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(slots=True)
class SkillDiscoveryResult:
    skills: list[SkillInfo]
    errors: list[SkillLoadError]
    roots: list[str]


class SkillManager:
    def __init__(self, workspace: Path, *, extra_paths: list[str] | None = None, home: Path | None = None) -> None:
        self.workspace = workspace.resolve()
        self.extra_paths = list(extra_paths or [])
        self.home = home or Path.home()
        self._result: SkillDiscoveryResult | None = None

    def refresh(self) -> SkillDiscoveryResult:
        state: dict[str, SkillInfo] = {}
        errors: list[SkillLoadError] = []
        roots: list[str] = []
        for root, pattern, source, scope in self._scan_specs():
            if not root.exists() or not root.is_dir():
                continue
            root_text = str(root)
            if root_text not in roots:
                roots.append(root_text)
            for path in sorted(root.glob(pattern)):
                if not path.is_file() or path.name != "SKILL.md":
                    continue
                parsed = self._parse_info(path, source=source, scope=scope, errors=errors)
                if parsed is None:
                    continue
                if parsed.name in state:
                    errors.append(
                        SkillLoadError(
                            path=str(path),
                            type="duplicate_name",
                            message=f'duplicate skill "{parsed.name}"; replacing {state[parsed.name].location}',
                        )
                    )
                state[parsed.name] = parsed
        self._result = SkillDiscoveryResult(skills=sorted(state.values(), key=lambda item: item.name), errors=errors, roots=roots)
        return self._result

    def discover(self) -> SkillDiscoveryResult:
        if self._result is None:
            return self.refresh()
        return self._result

    def list(self) -> list[SkillInfo]:
        return self.discover().skills

    def errors(self) -> list[SkillLoadError]:
        return self.discover().errors

    def dirs(self) -> list[str]:
        return sorted({str(Path(item.location).parent) for item in self.list()})

    def get(self, name: str) -> LoadedSkill | None:
        info = next((item for item in self.list() if item.name == name), None)
        if info is None:
            return None
        path = Path(info.location)
        _frontmatter, content = _parse_frontmatter(path.read_text(encoding="utf-8"))
        files = sorted(str(child.relative_to(path.parent)) for child in path.parent.rglob("*") if child.is_file() and child.name != "SKILL.md")[:50]
        return LoadedSkill(info=info, content=content.strip(), files=files)

    def format_available(self, *, verbose: bool = False, skills: list[SkillInfo] | None = None) -> str:
        items = skills if skills is not None else self.list()
        if not items:
            return "No skills are currently available."
        if verbose:
            lines = ["<available_skills>"]
            for skill in items:
                lines.extend(
                    [
                        "  <skill>",
                        f"    <name>{skill.name}</name>",
                        f"    <description>{skill.description}</description>",
                        f"    <location>{Path(skill.location).as_uri()}</location>",
                        "  </skill>",
                    ]
                )
            lines.append("</available_skills>")
            return "\n".join(lines)
        return "\n".join(["## Available Skills", *[f"- **{skill.name}**: {skill.description}" for skill in items]])

    def _scan_specs(self):
        project = self.workspace
        specs = [
            (self.home / ".claude", "skills/**/SKILL.md", "claude", "global"),
            (self.home / ".agents", "skills/**/SKILL.md", "agents", "global"),
            (self.home / ".codex", "skills/**/SKILL.md", "codex", "global"),
            (self.home / ".config" / "opencode", "skill/**/SKILL.md", "opencode", "global"),
            (self.home / ".config" / "opencode", "skills/**/SKILL.md", "opencode", "global"),
            (self.home / ".opencode", "skill/**/SKILL.md", "opencode", "global"),
            (self.home / ".opencode", "skills/**/SKILL.md", "opencode", "global"),
            (project / ".claude", "skills/**/SKILL.md", "claude", "project"),
            (project / ".agents", "skills/**/SKILL.md", "agents", "project"),
            (project / ".opencode", "skill/**/SKILL.md", "opencode", "project"),
            (project / ".opencode", "skills/**/SKILL.md", "opencode", "project"),
        ]
        for extra in self.extra_paths:
            path = Path(extra).expanduser()
            if not path.is_absolute():
                path = project / path
            specs.append((path, "**/SKILL.md", "custom", "custom"))
        return specs

    def _parse_info(self, path: Path, *, source: str, scope: str, errors: list[SkillLoadError]) -> SkillInfo | None:
        try:
            data, content = _parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(SkillLoadError(path=str(path), type="frontmatter_error", message=str(exc)))
            return None
        name = str(data.get("name", "")).strip().strip('"').strip("'")
        description = str(data.get("description", "")).strip().strip('"').strip("'")
        if not name or not description:
            errors.append(SkillLoadError(path=str(path), type="missing_required_field", message="name and description are required"))
            return None
        if not NAME_RE.match(name):
            errors.append(
                SkillLoadError(
                    path=str(path),
                    type="invalid_name",
                    message="name must match ^[a-z0-9][a-z0-9._-]{0,63}$",
                )
            )
            return None
        if not content.strip():
            errors.append(SkillLoadError(path=str(path), type="empty_content", message="skill body must not be empty"))
            return None
        compatibility = _as_list(data.get("compatibility"))
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        license_value = data.get("license")
        return SkillInfo(
            name=name,
            description=description,
            location=str(path.resolve()),
            source=source,
            scope=scope,
            compatibility=compatibility,
            license=str(license_value).strip() if license_value else None,
            metadata=metadata,
        )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML-style frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("frontmatter closing --- not found")
    raw = text[4:end].strip("\n")
    body = text[end + len("\n---") :].lstrip("\n")
    return _parse_simple_yaml(raw), body


def _parse_simple_yaml(raw: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_map: str | None = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith(" ") and current_map:
            stripped = line.strip()
            if stripped.startswith("- "):
                target = result.get(current_map)
                if not isinstance(target, list):
                    target = []
                    result[current_map] = target
                target.append(_parse_scalar(stripped[2:].strip()))
                continue
            key, value = _split_yaml_pair(stripped)
            target = result.setdefault(current_map, {})
            if isinstance(target, dict):
                target[key] = _parse_scalar(value)
            continue
        key, value = _split_yaml_pair(line)
        if value == "":
            result[key] = {}
            current_map = key
        else:
            result[key] = _parse_scalar(value)
            current_map = None
    return result


def _split_yaml_pair(line: str) -> tuple[str, str]:
    if ":" not in line:
        raise ValueError(f"invalid frontmatter line: {line}")
    key, value = line.split(":", 1)
    return key.strip(), value.strip()


def _parse_scalar(value: str) -> Any:
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in inner.split(",")]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
