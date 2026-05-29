"""Web access configuration — reads and writes the web_access block in an agent's config.yaml."""

import os
import yaml
from pathlib import Path

_DEFAULTS: dict = {
    "enabled": False,
    "search_provider": "duckduckgo",
    "searxng_url": None,
    "fetch_enabled": True,
}


class WebConfig:
    def __init__(self, agent_dir: Path) -> None:
        self._path = agent_dir / "config.yaml"
        self._data = self._load()

    def _load(self) -> dict:
        if not self._path.exists():
            return dict(_DEFAULTS)
        with open(self._path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return {**_DEFAULTS, **raw.get("web_access", {})}

    def save(self) -> None:
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}
        raw["web_access"] = self._data
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(raw, f, default_flow_style=False)

    @property
    def enabled(self) -> bool:
        return bool(self._data.get("enabled"))

    @property
    def search_provider(self) -> str:
        return str(self._data.get("search_provider", "duckduckgo"))

    @property
    def brave_api_key(self) -> str | None:
        return os.environ.get("BRAVE_API_KEY") or None

    @property
    def searxng_url(self) -> str | None:
        return self._data.get("searxng_url")

    @property
    def fetch_enabled(self) -> bool:
        return bool(self._data.get("fetch_enabled", True))

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if k in _DEFAULTS:
                self._data[k] = v
