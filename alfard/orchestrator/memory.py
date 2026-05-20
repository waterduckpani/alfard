"""Session memory — holds conversation history and injects the system prompt
on every get_messages() call."""

import json


class Memory:

    def __init__(self, system_prompt: str) -> None:
        self._system_prompt: str = system_prompt
        self._messages: list[dict] = []
        self._turn_count: int = 0

    def add_user(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})
        self._turn_count += 1

    def add_assistant(self, content: str) -> None:
        self._messages.append({"role": "assistant", "content": content})

    def add_assistant_tool_calls(self, tool_calls: list[dict]) -> None:
        self._messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    },
                }
                for tc in tool_calls
            ],
        })

    def add_tool_result(self, tool_call_id: str, result: any) -> None:
        self._messages.append({"role": "tool", "content": str(result), "tool_call_id": tool_call_id})

    def get_messages(self) -> list[dict]:
        return [{"role": "system", "content": self._system_prompt}] + self._messages

    def reset(self) -> None:
        self._messages = []
        self._turn_count = 0

    def turn_count(self) -> int:
        return self._turn_count
