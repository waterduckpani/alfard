"""Handles all OpenAI-compatible providers — OpenRouter, OpenAI, Ollama, LM Studio — using the
openai Python SDK with a custom base_url."""

import json

import openai

# Handles: openrouter, openai, ollama, lmstudio
# All four speak the OpenAI chat completions format at different base URLs


class OpenAICompatAdapter:

    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.base_url = base_url

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        kwargs = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"OpenAI-compat provider at {self.base_url!r} ({self.model}): {exc}"
            ) from exc

        message = response.choices[0].message

        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                }
                for tc in message.tool_calls
            ]

        return {
            "content": message.content,
            "tool_calls": tool_calls,
            "raw": response,
        }
