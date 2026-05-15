"""Audit logger — writes structured JSONL event records for all agent actions and tool calls."""

import json
import yaml
from datetime import datetime
from pathlib import Path


def _get_log_path() -> Path:
    config_path = Path(__file__).parent.parent.parent / "config" / "alfard.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    log_path_str = (config.get("audit") or {}).get("log_path", "logs/audit.jsonl")
    project_root = config_path.parent.parent
    log_path = project_root / log_path_str
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


class AuditLogger:

    def __init__(self) -> None:
        self.log_path = _get_log_path()
        self._fh = open(self.log_path, "a", encoding="utf-8", buffering=1)

    def _write(self, event: dict) -> None:
        event["timestamp"] = datetime.utcnow().isoformat() + "Z"
        self._fh.write(json.dumps(event) + "\n")

    def log_llm_call(self, provider: str, model: str, message_count: int, response: dict) -> None:
        self._write({
            "type": "llm_call",
            "provider": provider,
            "model": model,
            "message_count": message_count,
            "response_type": "tool_call" if response["tool_calls"] else "text",
        })

    def log_tool_call(self, tool_name: str, arguments: dict, source: str) -> None:
        self._write({
            "type": "tool_call",
            "tool_name": tool_name,
            "arguments": arguments,
            "source": source,
        })

    def log_gate_decision(self, tool_name: str, arguments: dict, decision: str, source: str) -> None:
        self._write({
            "type": "gate_decision",
            "tool_name": tool_name,
            "arguments": arguments,
            "decision": decision,
            "source": source,
        })

    def close(self) -> None:
        self._fh.close()
