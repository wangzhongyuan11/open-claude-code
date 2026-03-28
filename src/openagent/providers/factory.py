from __future__ import annotations

from dataclasses import replace

from openagent.config.settings import Settings
from openagent.domain.messages import ModelRef
from openagent.providers.base import BaseProvider


def build_provider(settings: Settings, model_override: ModelRef | None = None) -> BaseProvider:
    effective = settings
    if model_override is not None:
        provider_name = model_override.provider_id
        effective = replace(settings, provider_name=provider_name, model=model_override.model_id)
    provider_name = effective.provider_name.lower()
    if provider_name == "anthropic":
        from openagent.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model=effective.model)
    if provider_name == "volcengine":
        from openagent.providers.volcengine import VolcengineProvider

        return VolcengineProvider(
            model=effective.model,
            base_url=effective.base_url,
            api_key=effective.api_key,
        )
    raise ValueError(f"unsupported provider: {effective.provider_name}")
