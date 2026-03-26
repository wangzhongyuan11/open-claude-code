from __future__ import annotations

from openagent.extensions.base import ExtensionContext, PermissionDecision, PermissionPolicy


class AllowAllPolicy(PermissionPolicy):
    def check(self, context: ExtensionContext) -> PermissionDecision:
        return PermissionDecision(allowed=True)
