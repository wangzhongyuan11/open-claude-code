from __future__ import annotations

from dataclasses import dataclass, field
import re

from openagent.agent.profile import AgentProfile
from openagent.skill.models import SkillInfo


WORD_RE = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)
CJK_HINTS = [
    "旅行研究",
    "博物馆",
    "古建",
    "出发前功课",
    "创建 skill",
    "创建技能",
    "技能",
    "文档",
]
STOPWORDS = {
    "and",
    "are",
    "for",
    "how",
    "the",
    "this",
    "use",
    "using",
    "when",
    "with",
}


@dataclass(slots=True)
class SkillMatch:
    skill: SkillInfo
    score: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.skill.name,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "location": self.skill.location,
        }


class SkillSelector:
    def __init__(self, *, min_score: float = 4.0, limit: int = 1) -> None:
        self.min_score = min_score
        self.limit = limit

    def select(
        self,
        *,
        user_text: str,
        profile: AgentProfile,
        skills: list[SkillInfo],
    ) -> list[SkillMatch]:
        matches: list[SkillMatch] = []
        for skill in skills:
            score, reasons = self._score(user_text=user_text, profile=profile, skill=skill)
            if score >= self.min_score:
                matches.append(SkillMatch(skill=skill, score=score, reasons=reasons))
        matches.sort(key=lambda item: (-item.score, item.skill.name))
        return matches[: self.limit]

    def _score(self, *, user_text: str, profile: AgentProfile, skill: SkillInfo) -> tuple[float, list[str]]:
        user = _normalize(user_text)
        agent = _normalize(" ".join([profile.name, profile.description or "", profile.prompt or ""]))
        description = _normalize(skill.description)
        metadata = _normalize(" ".join(str(value) for value in skill.metadata.values()))
        name = _normalize(skill.name)
        haystack = " ".join([name, description, metadata])

        score = 0.0
        reasons: list[str] = []

        if name and name in user:
            score += 12
            reasons.append("skill-name-mentioned")

        name_tokens = set(_tokens(name))
        user_tokens = set(_tokens(user))
        desc_tokens = set(_tokens(description))
        metadata_tokens = set(_tokens(metadata))
        agent_tokens = set(_tokens(agent))
        haystack_tokens = name_tokens | desc_tokens | metadata_tokens

        name_overlap = sorted(name_tokens & user_tokens)
        if name_overlap:
            value = 3.0 * len(name_overlap)
            score += value
            reasons.append("name-token-overlap:" + ",".join(name_overlap[:4]))

        desc_overlap = sorted((desc_tokens | metadata_tokens) & user_tokens)
        if desc_overlap:
            value = min(8.0, 1.4 * len(desc_overlap))
            score += value
            reasons.append("description-overlap:" + ",".join(desc_overlap[:6]))

        role_overlap = sorted((desc_tokens | metadata_tokens | name_tokens) & agent_tokens & user_tokens)
        if role_overlap:
            score += min(3.0, 1.0 * len(role_overlap))
            reasons.append("agent-role-overlap:" + ",".join(role_overlap[:4]))

        phrase_hits = [phrase for phrase in CJK_HINTS if phrase in user and phrase in haystack]
        if phrase_hits:
            score += 5.0 + len(phrase_hits)
            reasons.append("phrase-match:" + ",".join(phrase_hits[:3]))

        if "openai" in user_tokens and "openai" in name_tokens:
            score += 5.0
            reasons.append("openai-task")
        if {"skill", "skills"} & user_tokens and ({"creator", "creating", "create", "updating", "update"} & haystack_tokens):
            score += 4.0
            reasons.append("skill-authoring-task")
        if "travel" in user_tokens and "travel" in haystack:
            score += 4.0
            reasons.append("travel-task")
        if "cloudflare" in user_tokens and "cloudflare" in haystack:
            score += 6.0
            reasons.append("cloudflare-task")
        if "agent" in user_tokens and "sdk" in user_tokens and "agents-sdk" in name:
            score += 6.0
            reasons.append("agents-sdk-task")

        return score, reasons


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().replace("_", "-").split())


def _tokens(text: str) -> list[str]:
    normalized = (text or "").replace("-", " ").replace("_", " ").replace(".", " ")
    return [item.group(0) for item in WORD_RE.finditer(normalized) if len(item.group(0)) >= 3 and item.group(0) not in STOPWORDS]
