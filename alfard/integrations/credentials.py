"""Credentials manager — loads and resolves API keys and service credentials from environment variables."""

import os
from dotenv import load_dotenv


# Security invariant: credentials are never passed to the LLM or
# written to the audit log. They are injected into tool kwargs at
# execution time only and exist in memory for that call alone.
class CredentialsManager:

    def __init__(self) -> None:
        load_dotenv()
        self._store: dict[str, str] = {}

    def register(self, name: str, env_var: str) -> None:
        value = os.environ.get(env_var)
        if value is None:
            raise RuntimeError(
                f"Credential '{name}' requires env var '{env_var}' which is not set"
            )
        self._store[name] = value

    def get(self, name: str) -> str:
        if name in self._store:
            return self._store[name]
        registered = list(self._store.keys())
        raise RuntimeError(
            f"Credential '{name}' not found. Registered credentials: {registered}"
        )

    def is_registered(self, name: str) -> bool:
        return name in self._store

    def inject(self, tool_arguments: dict, credential_map: dict[str, str]) -> dict:
        result = dict(tool_arguments)
        for arg_key, cred_name in credential_map.items():
            result[arg_key] = self.get(cred_name)
        return result
