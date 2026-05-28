"""Embedding client — generates vector embeddings for memory
retrieval using the same API key as the main LLM provider."""

import os
import numpy as np
import yaml
from alfard.paths import ALFARD_HOME, load_env

EMBEDDING_MODELS = {
    "openrouter": "openai/text-embedding-3-small",
    "openai":     "openai/text-embedding-3-small",
    "anthropic":  "qwen/qwen3-embedding-0.6b",
    "ollama":     "nomic-embed-text",
    "lmstudio":   "nomic-embed-text",
}

BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai":     "https://api.openai.com/v1",
    "anthropic":  "https://openrouter.ai/api/v1",
    "ollama":     "http://localhost:11434/v1",
    "lmstudio":   "http://localhost:1234/v1",
}

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"


def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def get_embedding(text: str) -> list[float]:
    """
    Generate an embedding vector for the given text.
    Uses the same provider and API key as the main LLM.
    Returns a list of floats (the embedding vector).
    """
    load_env()
    from openai import OpenAI

    cfg = _load_config()
    provider = cfg.get("provider", {}).get("name", "openrouter")
    model = EMBEDDING_MODELS.get(provider, "qwen/qwen3-embedding-0.6b")
    base_url = BASE_URLS.get(provider, "https://openrouter.ai/api/v1")

    # Get API key from environment
    env_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai":     "OPENAI_API_KEY",
        "anthropic":  "OPENROUTER_API_KEY",  # use openrouter for embeddings
        "ollama":     "ollama",
        "lmstudio":   "lmstudio",
    }
    api_key = os.environ.get(env_map.get(provider, "OPENROUTER_API_KEY"), "none")

    try:
        client = OpenAI(base_url=base_url, api_key=api_key)
        response = client.embeddings.create(model=model, input=text)
        return response.data[0].embedding
    except Exception as e:
        raise RuntimeError(
            f"Embedding API call failed ({provider}/{model}): {e}\n"
            f"Check your API key and network connection."
        ) from e


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))
