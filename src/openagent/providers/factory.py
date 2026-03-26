from __future__ import annotations

from openagent.config.settings import Settings
from openagent.providers.base import BaseProvider


def build_provider(settings: Settings) -> BaseProvider:
    provider_name = settings.provider_name.lower()
    if provider_name == "anthropic":
        from openagent.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model=settings.model)
    if provider_name == "volcengine":
        from openagent.providers.volcengine import VolcengineProvider

        return VolcengineProvider(
            model=settings.model,
            base_url=settings.base_url,
            api_key=settings.api_key,
        )
    raise ValueError(f"unsupported provider: {settings.provider_name}")
