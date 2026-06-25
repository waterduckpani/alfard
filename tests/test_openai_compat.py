"""Test suite for OpenAICompatAdapter (OpenRouter, OpenAI, Ollama, LM Studio).

The adapter wraps the `openai` SDK client. Each test swaps in a MagicMock for
`adapter.client` so no real network call happens, then exercises `complete()`
and asserts the normalized response shape is correct.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import openai
import pytest

from alfard.llm.adapters.openai_compat import OpenAICompatAdapter


@pytest.fixture
def adapter():
    """Adapter with its SDK client swapped for a mock."""
    a = OpenAICompatAdapter(
        base_url="https://api.example.com/v1", api_key="test-key", model="test-model"
    )
    a.client = MagicMock()
    return a


# ── SUCCESS ───────────────────────────────────────────────────────────────────

def test_success_returns_text_content(adapter):
    message = SimpleNamespace(content="Hello there!", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    adapter.client.chat.completions.create.return_value = response

    result = adapter.complete([{"role": "user", "content": "hi"}])

    assert result["content"] == "Hello there!"
    assert result["tool_calls"] is None
    assert result["raw"] is response


def test_tools_omitted_when_not_provided(adapter):
    message = SimpleNamespace(content="ok", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    adapter.client.chat.completions.create.return_value = response

    adapter.complete([{"role": "user", "content": "hi"}])

    _, kwargs = adapter.client.chat.completions.create.call_args
    assert "tools" not in kwargs


# ── TOOL CALL ─────────────────────────────────────────────────────────────────

def test_tool_call_normalizes_arguments(adapter):
    tool_call = SimpleNamespace(
        id="call_123",
        function=SimpleNamespace(
            name="get_weather", arguments=json.dumps({"city": "Bengaluru"})
        ),
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    adapter.client.chat.completions.create.return_value = response

    result = adapter.complete(
        [{"role": "user", "content": "weather?"}], tools=[{"type": "function"}]
    )

    assert result["content"] is None
    assert result["tool_calls"] == [
        {"id": "call_123", "name": "get_weather", "arguments": {"city": "Bengaluru"}}
    ]
    _, kwargs = adapter.client.chat.completions.create.call_args
    assert kwargs["tools"] == [{"type": "function"}]


def test_multiple_tool_calls_all_normalized(adapter):
    tc1 = SimpleNamespace(
        id="call_1", function=SimpleNamespace(name="fn_a", arguments="{}")
    )
    tc2 = SimpleNamespace(
        id="call_2",
        function=SimpleNamespace(name="fn_b", arguments=json.dumps({"x": 1})),
    )
    message = SimpleNamespace(content=None, tool_calls=[tc1, tc2])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    adapter.client.chat.completions.create.return_value = response

    result = adapter.complete([{"role": "user", "content": "do both"}])

    assert result["tool_calls"] == [
        {"id": "call_1", "name": "fn_a", "arguments": {}},
        {"id": "call_2", "name": "fn_b", "arguments": {"x": 1}},
    ]


# ── ERROR ─────────────────────────────────────────────────────────────────────

def test_sdk_exception_wrapped_in_runtime_error(adapter):
    adapter.client.chat.completions.create.side_effect = ValueError("rate limited")

    with pytest.raises(RuntimeError) as exc_info:
        adapter.complete([{"role": "user", "content": "hi"}])

    message = str(exc_info.value)
    assert "test-model" in message
    assert "api.example.com" in message
    assert exc_info.value.__cause__ is not None


def test_rate_limit_error_surfaces_as_runtime_error(adapter):
    """A real 429 from the SDK must propagate, not be silently retried or swallowed."""
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    rate_limit_error = openai.RateLimitError(
        "Rate limit exceeded", response=response, body=None
    )
    adapter.client.chat.completions.create.side_effect = rate_limit_error

    with pytest.raises(RuntimeError) as exc_info:
        adapter.complete([{"role": "user", "content": "hi"}])

    assert "Rate limit exceeded" in str(exc_info.value)
    assert exc_info.value.__cause__ is rate_limit_error
    # Only one call was attempted — no silent retry loop.
    assert adapter.client.chat.completions.create.call_count == 1


# ── EMPTY CONTENT ──────────────────────────────────────────────────────────────

def test_empty_string_content_not_coerced_to_none(adapter):
    """An empty-string message (distinct from no content at all) must be preserved as-is."""
    message = SimpleNamespace(content="", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    adapter.client.chat.completions.create.return_value = response

    result = adapter.complete([{"role": "user", "content": "hi"}])

    assert result["content"] == ""
    assert result["content"] is not None