from __future__ import annotations

import json
from pathlib import Path

from openagent.agent.profile import AgentProfile
from openagent.domain.messages import ModelRef
from openagent.permission.models import PermissionRule


class AgentStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def save(self, profile: AgentProfile) -> Path:
        path = self.path_for(profile.name)
        frontmatter = {
            "name": profile.name,
            "description": profile.description,
            "mode": profile.mode,
            "hidden": "true" if profile.hidden else "false",
            "steps": str(profile.steps or ""),
            "temperature": str(profile.temperature or ""),
            "top_p": str(profile.top_p or ""),
            "variant": profile.variant or "",
            "color": profile.color or "",
            "inherits_default_prompt": "true" if profile.inherits_default_prompt else "false",
        }
        if profile.model is not None:
            frontmatter["provider"] = profile.model.provider_id
            frontmatter["model"] = profile.model.model_id
        if profile.allowed_tools is not None:
            frontmatter["allowed_tools"] = ",".join(sorted(profile.allowed_tools))
        if profile.permission_rules:
            frontmatter["permission_rules_json"] = json.dumps(
                [rule.to_dict() for rule in profile.permission_rules],
                ensure_ascii=False,
            )
        lines = ["---"]
        for key, value in frontmatter.items():
            if value == "":
                continue
            lines.append(f"{key}: {value}")
        lines.append("---")
        lines.append("")
        lines.append(profile.prompt or "")
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return path

    def load_all(self) -> list[AgentProfile]:
        profiles: list[AgentProfile] = []
        for path in sorted(self.root.glob("*.md")):
            try:
                profiles.append(self._load_markdown(path))
            except Exception:
                continue
        return profiles

    def get(self, name: str) -> AgentProfile | None:
        path = self.path_for(name)
        if not path.exists():
            return None
        return self._load_markdown(path)

    def _load_markdown(self, path: Path) -> AgentProfile:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"invalid agent markdown: {path}")
        _, rest = text.split("---\n", 1)
        frontmatter_text, body = rest.split("\n---\n", 1)
        metadata: dict[str, str] = {}
        for line in frontmatter_text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
        model = None
        if metadata.get("provider") and metadata.get("model"):
            model = ModelRef(provider_id=metadata["provider"], model_id=metadata["model"])
        allowed_tools = None
        if metadata.get("allowed_tools"):
            allowed_tools = {item.strip() for item in metadata["allowed_tools"].split(",") if item.strip()}
        permission_rules: list[PermissionRule] = []
        if metadata.get("permission_rules_json"):
            try:
                permission_rules = [PermissionRule.from_dict(item) for item in json.loads(metadata["permission_rules_json"])]
            except Exception:
                permission_rules = []
        return AgentProfile(
            name=metadata.get("name") or path.stem,
            description=metadata.get("description", ""),
            mode=metadata.get("mode", "all"),  # type: ignore[arg-type]
            hidden=metadata.get("hidden", "false").lower() == "true",
            prompt=body.strip(),
            model=model,
            variant=metadata.get("variant") or None,
            temperature=float(metadata["temperature"]) if metadata.get("temperature") else None,
            top_p=float(metadata["top_p"]) if metadata.get("top_p") else None,
            color=metadata.get("color") or None,
            steps=int(metadata["steps"]) if metadata.get("steps") else None,
            inherits_default_prompt=metadata.get("inherits_default_prompt", "true").lower() == "true",
            allowed_tools=allowed_tools,
            permission_rules=permission_rules,
            native=False,
        )
