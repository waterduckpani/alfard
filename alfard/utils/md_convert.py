"""Markdown conversion utilities — convert CommonMark to platform-specific formats."""

import re


# ── shared helpers ─────────────────────────────────────────────────────────────


def _protect_code(text: str) -> tuple[str, dict[str, str]]:
    """Replace fenced and inline code with opaque placeholders, return (text, stash)."""
    stash: dict[str, str] = {}
    counter = [0]

    def _store(raw: str) -> str:
        key = f"\x00P{counter[0]}\x00"
        stash[key] = raw
        counter[0] += 1
        return key

    text = re.sub(r'```[\s\S]*?```|~~~[\s\S]*?~~~', lambda m: _store(m.group(0)), text)
    text = re.sub(r'`[^`\n]+`', lambda m: _store(m.group(0)), text)
    return text, stash


def _restore(text: str, stash: dict[str, str]) -> str:
    for key, original in stash.items():
        text = text.replace(key, original)
    return text


def _stash_bold(text: str) -> tuple[str, list[str]]:
    """Extract **bold** and __bold__ spans into a stash so italic regex can't touch them."""
    parts: list[str] = []

    def _replace(m: re.Match) -> str:
        parts.append(m.group(1))
        return f"\x00BOLD{len(parts) - 1}\x00"

    text = re.sub(r'\*\*(.+?)\*\*', _replace, text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', _replace, text, flags=re.DOTALL)
    return text, parts


# ── public converters ──────────────────────────────────────────────────────────


def to_slack(text: str) -> str:
    """Convert CommonMark markdown to Slack mrkdwn format."""
    text, code_stash = _protect_code(text)

    # Strip HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Strip horizontal rules (--- / *** / ___)
    text = re.sub(r'^[ \t]*(?:[-*_][ \t]*){3,}$', '', text, flags=re.MULTILINE)
    # ~~strike~~ → ~strike~
    text = re.sub(r'~~(.+?)~~', r'~\1~', text, flags=re.DOTALL)
    # [text](url) → <url|text>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', text)

    # Protect bold so the italic pass can't touch it
    text, bold_parts = _stash_bold(text)

    # *italic* → _italic_
    text = re.sub(r'\*(.+?)\*', r'_\1_', text, flags=re.DOTALL)

    # Restore bold as *content*
    for i, content in enumerate(bold_parts):
        text = text.replace(f"\x00BOLD{i}\x00", f'*{content}*')

    # Headings AFTER italic pass so *Heading* is not re-matched as italic
    text = re.sub(r'^#{1,6}[ \t]+(.+?)[ \t]*$', r'*\1*', text, flags=re.MULTILINE)

    # Bullet lines (- item or * item) → • item
    text = re.sub(r'^[ \t]*[-*][ \t]+', '• ', text, flags=re.MULTILINE)

    return _restore(text, code_stash)


def to_telegram_html(text: str) -> str:
    """Convert CommonMark markdown to Telegram HTML parse mode."""
    # Extract code blocks first, converting their content to HTML-safe form.
    fenced_out: list[str] = []
    inline_out: list[str] = []

    def _fenced(m: re.Match) -> str:
        raw = m.group(0)
        inner = re.sub(r'^```[^\n]*\n?', '', raw)
        inner = re.sub(r'\n?```$', '', inner)
        escaped = inner.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        fenced_out.append(f'<pre>{escaped}</pre>')
        return f"\x00F{len(fenced_out) - 1}\x00"

    def _inline(m: re.Match) -> str:
        inner = m.group(0)[1:-1]
        escaped = inner.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        inline_out.append(f'<code>{escaped}</code>')
        return f"\x00I{len(inline_out) - 1}\x00"

    text = re.sub(r'```[\s\S]*?```', _fenced, text)
    text = re.sub(r'`[^`\n]+`', _inline, text)

    # Escape bare & < > in the remaining text (Telegram rejects unescaped ones)
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Strip horizontal rules
    text = re.sub(r'^[ \t]*(?:[-*_][ \t]*){3,}$', '', text, flags=re.MULTILINE)
    # Headings → <b>Heading</b>
    text = re.sub(r'^#{1,6}[ \t]+(.+?)[ \t]*$', r'<b>\1</b>', text, flags=re.MULTILINE)
    # ~~strike~~ → <s>strike</s>
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text, flags=re.DOTALL)
    # [text](url) → <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Protect bold before italic pass
    text, bold_parts = _stash_bold(text)

    # *italic* → <i>italic</i>
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text, flags=re.DOTALL)
    # _italic_ → <i>italic</i>  (word-boundary guard to avoid matching snake_case)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<i>\1</i>', text, flags=re.DOTALL)

    # Restore bold as <b>content</b>
    for i, content in enumerate(bold_parts):
        text = text.replace(f"\x00BOLD{i}\x00", f'<b>{content}</b>')

    # Bullet lines → • item
    text = re.sub(r'^[ \t]*[-*][ \t]+', '• ', text, flags=re.MULTILINE)

    # Restore code spans
    for i, s in enumerate(fenced_out):
        text = text.replace(f"\x00F{i}\x00", s)
    for i, s in enumerate(inline_out):
        text = text.replace(f"\x00I{i}\x00", s)

    return text


def to_discord(text: str) -> str:
    """Sanitise CommonMark for Discord — flatten oversized headings to bold."""
    # Discord renders CommonMark natively; h1-h6 look oversized, flatten to **bold**
    text = re.sub(r'^#{1,6}[ \t]+(.+?)[ \t]*$', r'**\1**', text, flags=re.MULTILINE)
    return text


if __name__ == "__main__":
    sample = """
### Task List
- **High priority** task
- _Italic note_ about something
`inline code` here
**Summary:** all done
[Link text](https://example.com)
"""

    print("=== SLACK ===")
    print(to_slack(sample))
    print("=== TELEGRAM HTML ===")
    print(to_telegram_html(sample))
    print("=== DISCORD ===")
    print(to_discord(sample))
