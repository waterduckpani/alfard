"""Registry of supported LLM providers and their connection metadata."""

PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "adapter": "openai_compat",
        "local": False,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "adapter": "openai_compat",
        "local": False,
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "api_key_env": "ANTHROPIC_API_KEY",
        "adapter": "anthropic",
        "local": False,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "api_key_env": "",
        "adapter": "openai_compat",
        "local": True,
    },
    "lmstudio": {
        "base_url": "http://localhost:1234/v1",
        "api_key_env": "",
        "adapter": "openai_compat",
        "local": True,
    },
}


def get_provider(name: str) -> dict:
    if name in PROVIDERS:
        return PROVIDERS[name]
    available = ", ".join(PROVIDERS)
    raise ValueError(f"Unknown provider {name!r}. Available providers: {available}")
