"""LLM client router — reads provider from config/alfard.yaml and returns the correct adapter."""

import os

import yaml

from alfard.llm.providers import get_provider
from alfard.llm.adapters.openai_compat import OpenAICompatAdapter
from alfard.llm.adapters.anthropic_adapter import AnthropicAdapter
from alfard.paths import ALFARD_HOME, load_env

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"


class LLMClient:

    def __init__(self):
        load_env()

        try:
            with open(_CONFIG_PATH) as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            raise RuntimeError(
                "No configuration found. Run 'alfard setup' to get started."
            ) from None

        provider_cfg = config["provider"]
        name = provider_cfg["name"]
        model = provider_cfg["model"]
        base_url = provider_cfg.get("base_url")
        api_key_env = provider_cfg.get("api_key_env", "")

        provider = get_provider(name)

        if api_key_env:
            api_key = os.environ.get(api_key_env)
            if not api_key:
                raise RuntimeError(
                    f"Provider {name!r} requires env var {api_key_env!r} but it is not set"
                )
        else:
            api_key = "local"

        effective_base_url = base_url or provider["base_url"]

        if provider["adapter"] == "anthropic":
            self.adapter = AnthropicAdapter(api_key, model)
        else:
            self.adapter = OpenAICompatAdapter(effective_base_url, api_key, model)

        self.provider_name = name
        self.model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        return self.adapter.complete(messages, tools)
