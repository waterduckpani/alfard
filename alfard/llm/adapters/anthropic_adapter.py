"""Handles Anthropic API directly using the anthropic SDK."""

import anthropic

# Handles: anthropic
# Uses the anthropic SDK directly — different response format from OpenAI compat


class AnthropicAdapter:

    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        kwargs = {"model": self.model, "max_tokens": 8096, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        try:
            response = self.client.messages.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(f"Anthropic ({self.model}): {exc}") from exc

        text_blocks = [b.text for b in response.content if b.type == "text"]
        content = "\n".join(text_blocks) if text_blocks else None

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        tool_calls = (
            [{"name": b.name, "arguments": b.input} for b in tool_use_blocks]
            if tool_use_blocks
            else None
        )

        return {
            "content": content,
            "tool_calls": tool_calls,
            "raw": response,
        }
