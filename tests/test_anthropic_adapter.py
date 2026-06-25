"""Test suite for AnthropicAdapter.

The adapter wraps the `anthropic` SDK client directly. Each test swaps in a
MagicMock for `adapter.client` so no real network call happens, then
exercises `complete()` and asserts the normalized response shape is correct.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from alfard.llm.adapters.anthropic_adapter import AnthropicAdapter


@pytest.fixture
def adapter():
    """Adapter with its SDK client swapped for a mock."""
    a = AnthropicAdapter(api_key="test-key", model="claude-test")
    a.client = MagicMock()
    return a


# ── SUCCESS ───────────────────────────────────────────────────────────────────

def test_success_returns_text_content(adapter):
    block = SimpleNamespace(type="text", text="Hello there!")
    response = SimpleNamespace(content=[block])
    adapter.client.messages.create.return_value = response

    result = adapter.complete([{"role": "user", "content": "hi"}])

    assert result["content"] == "Hello there!"
    assert result["tool_calls"] is None
    assert result["raw"] is response


def test_multiple_text_blocks_are_joined_with_newline(adapter):
    blocks = [
        SimpleNamespace(type="text", text="first part"),
        SimpleNamespace(type="text", text="second part"),
    ]
    response = SimpleNamespace(content=blocks)
    adapter.client.messages.create.return_value = response

    result = adapter.complete([{"role": "user", "content": "hi"}])

    assert result["content"] == "first part\nsecond part"


def test_tools_omitted_when_not_provided(adapter):
    block = SimpleNamespace(type="text", text="ok")
    response = SimpleNamespace(content=[block])
    adapter.client.messages.create.return_value = response

    adapter.complete([{"role": "user", "content": "hi"}])

    _, kwargs = adapter.client.messages.create.call_args
    assert "tools" not in kwargs
    assert kwargs["max_tokens"] == 8096


# ── TOOL CALL ─────────────────────────────────────────────────────────────────

def test_tool_use_block_normalized(adapter):
    block = SimpleNamespace(type="tool_use", name="get_weather", input={"city": "Bengaluru"})
    response = SimpleNamespace(content=[block])
    adapter.client.messages.create.return_value = response

    result = adapter.complete(
        [{"role": "user", "content": "weather?"}], tools=[{"name": "get_weather"}]
    )

    assert result["content"] is None
    assert result["tool_calls"] == [{"name": "get_weather", "arguments": {"city": "Bengaluru"}}]
    _, kwargs = adapter.client.messages.create.call_args
    assert kwargs["tools"] == [{"name": "get_weather"}]


def test_mixed_text_and_tool_use_blocks(adapter):
    blocks = [
        SimpleNamespace(type="text", text="Let me check that."),
        SimpleNamespace(type="tool_use", name="get_weather", input={"city": "Delhi"}),
    ]
    response = SimpleNamespace(content=blocks)
    adapter.client.messages.create.return_value = response

    result = adapter.complete([{"role": "user", "content": "weather?"}])

    assert result["content"] == "Let me check that."
    assert result["tool_calls"] == [{"name": "get_weather", "arguments": {"city": "Delhi"}}]


# ── ERROR ─────────────────────────────────────────────────────────────────────

def test_sdk_exception_wrapped_in_runtime_error(adapter):
    adapter.client.messages.create.side_effect = ValueError("rate limited")

    with pytest.raises(RuntimeError) as exc_info:
        adapter.complete([{"role": "user", "content": "hi"}])

    message = str(exc_info.value)
    assert "claude-test" in message
    assert exc_info.value.__cause__ is not None


def test_rate_limit_error_surfaces_as_runtime_error(adapter):
    """A real 429 from the SDK must propagate, not be silently retried or swallowed."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code=429, request=request)
    rate_limit_error = anthropic.RateLimitError(
        "Rate limit exceeded", response=response, body=None
    )
    adapter.client.messages.create.side_effect = rate_limit_error

    with pytest.raises(RuntimeError) as exc_info:
        adapter.complete([{"role": "user", "content": "hi"}])

    assert "Rate limit exceeded" in str(exc_info.value)
    assert exc_info.value.__cause__ is rate_limit_error
    # Only one call was attempted — no silent retry loop.
    assert adapter.client.messages.create.call_count == 1


# ── EMPTY CONTENT ──────────────────────────────────────────────────────────────

def test_empty_string_text_block_not_coerced_to_none(adapter):
    """An empty-string text block (distinct from no text blocks at all) must be preserved."""
    block = SimpleNamespace(type="text", text="")
    response = SimpleNamespace(content=[block])
    adapter.client.messages.create.return_value = response

    result = adapter.complete([{"role": "user", "content": "hi"}])

    assert result["content"] == ""
    assert result["content"] is not None