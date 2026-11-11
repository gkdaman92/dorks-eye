"""AI operators. `build_agent` picks a backend by provider name."""

from __future__ import annotations

from .openai_compat import PRESETS
from .tools import ToolExecutor

PROVIDERS = ["anthropic", *PRESETS, "custom"]


def build_agent(provider: str, executor: ToolExecutor, **kw):
    provider = (provider or "anthropic").lower()
    if provider in ("anthropic", "claude"):
        from .anthropic_agent import AnthropicAgent

        kw.pop("api_key_env", None)
        return AnthropicAgent(executor, **kw)
    from .openai_compat import OpenAICompatAgent

    kw.pop("effort", None)
    return OpenAICompatAgent(executor, provider=provider, **kw)
