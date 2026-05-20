"""Audit logger — writes structured JSONL event records for all agent actions and tool calls."""

import json
import yaml
from datetime import datetime
from pathlib import Path

from alfard.paths import ALFARD_HOME


def _get_log_path() -> Path:
    config_path = ALFARD_HOME / "config" / "alfard.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    log_path_str = (config.get("audit") or {}).get("log_path", "logs/audit.jsonl")
    project_root = config_path.parent.parent
    log_path = project_root / log_path_str
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


_CORRECTION_SIGNALS = {"no", "wrong", "actually", "don't", "dont"}


class AuditLogger:

    def __init__(self, session_id: str | None = None) -> None:
        self.log_path = _get_log_path()
        self.session_id = session_id
        self._fh = open(self.log_path, "a", encoding="utf-8", buffering=1)
        self._tool_calls_total = 0
        self._tool_calls_failed = 0
        self._corrections_detected = 0

    def _write(self, event: dict) -> None:
        event["timestamp"] = datetime.utcnow().isoformat() + "Z"
        if self.session_id:
            event["session_id"] = self.session_id
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

    def log_session_start(self, agent_name: str, provider: str, model: str) -> None:
        self._write({
            "type": "session_start",
            "agent_name": agent_name,
            "provider": provider,
            "model": model,
        })

    def log_session_end(
        self,
        outcome: str,
        turns: int,
        tool_calls_total: int,
        tool_calls_failed: int,
        corrections_detected: int,
    ) -> None:
        self._write({
            "type": "session_end",
            "outcome": outcome,
            "turns": turns,
            "tool_calls_total": tool_calls_total,
            "tool_calls_failed": tool_calls_failed,
            "corrections_detected": corrections_detected,
        })

    def log_tool_result(self, tool_name: str, success: bool, error_message: str | None = None) -> None:
        self._tool_calls_total += 1
        if not success:
            self._tool_calls_failed += 1
        event: dict = {
            "type": "tool_result",
            "tool_name": tool_name,
            "success": success,
        }
        if error_message is not None:
            event["error_message"] = error_message
        self._write(event)

    def log_prompt_injection_warning(self, tool_name: str, approved: bool) -> None:
        self._write({
            "type": "prompt_injection_warning",
            "tool_name": tool_name,
            "approved": approved,
        })

    def log_user_correction(self, message: str) -> None:
        words = set(message.lower().split())
        signal = next((w for w in _CORRECTION_SIGNALS if w in words), None)
        if signal:
            self._corrections_detected += 1
            self._write({
                "type": "user_correction",
                "signal": signal,
            })

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False  # do not suppress exceptions

    def close(self) -> None:
        self._fh.close()
