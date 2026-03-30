from __future__ import annotations

from fnmatch import fnmatchcase

from openagent.permission.models import PermissionRule


def evaluate_rules(agent: str, permission: str, pattern: str, rulesets: list[list[PermissionRule]]) -> PermissionRule:
    match: PermissionRule | None = None
    for rules in rulesets:
        for rule in rules:
            if not fnmatchcase(agent, rule.agent) and not fnmatchcase(rule.agent, agent):
                continue
            if not fnmatchcase(permission, rule.permission) and not fnmatchcase(rule.permission, permission):
                continue
            if not fnmatchcase(pattern, rule.pattern) and not fnmatchcase(rule.pattern, pattern):
                continue
            match = rule
    return match or PermissionRule(permission=permission, pattern=pattern, action="ask", agent=agent)
