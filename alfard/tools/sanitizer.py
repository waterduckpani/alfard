"""Tool sanitizer — strips instruction-injection patterns from untrusted external content before it enters LLM context."""

import re

_BLOCK_TAGS = [
    (r"<system>.*?</system>", ""),
    (r"<instructions>.*?</instructions>", ""),
]

_PHRASE_PATTERNS = [
    r"ignore previous instructions[^\n]*",
    r"ignore all previous[^\n]*",
    r"you are now[^\n]*",
    r"your new instructions[^\n]*",
]

_SUSPICIOUS_PHRASES = [
    "ignore previous instructions",
    "ignore all previous",
    "you are now",
    "your new instructions",
    "disregard your",
    "forget your instructions",
]


def sanitize(text: str, source: str = "external") -> str:
    cleaned = text
    for pattern, replacement in _BLOCK_TAGS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE | re.DOTALL)
    for pattern in _PHRASE_PATTERNS:
        cleaned = re.sub(pattern, "[REDACTED]", cleaned, flags=re.IGNORECASE)
    return f"[SOURCE: {source.upper()}]\n{cleaned}\n[END SOURCE]"


def is_suspicious(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _SUSPICIOUS_PHRASES)
