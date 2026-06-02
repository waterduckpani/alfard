# Gmail Skill

If `gmail_list_messages` is not in your toolset, Gmail is not connected on this machine. Tell the user to run: `alfard connect gmail`

## Tools

**gmail_search_messages** — search by any Gmail query string (e.g. `from:alice@example.com`, `is:unread newer_than:3d`, `subject:invoice`). Use this to find messages before fetching them.

**gmail_list_messages** — list recent unread messages. Use as the default starting point when the user asks "what's in my inbox" or "any new emails".

**gmail_get_message** — fetch one message by id. Always obtain the id from a search or list result first — never guess.

**gmail_get_thread** — get a full conversation thread by thread id. Use when the user wants to see the whole reply chain.

**gmail_list_labels** — list all labels in the account. Use before labelling or filtering by label name.

**gmail_create_draft** — create a draft email. Always do this first when the user wants to send something, so they can review before sending.

**gmail_send_draft** — send an existing draft by its draft ID. Use this whenever the user asks to send a draft. Never reconstruct a draft by fetching it with `gmail_get_draft` and re-sending with `gmail_send_message` — that strips HTML formatting.

**gmail_send_message** — send an email. Always confirm with the user before sending.

**gmail_thread_modify** — archive, label, or move a thread. Use to organise mail on the user's behalf after confirmation.

## Rules

- Always create a draft first; only send after the user says "yes, send it" or equivalent.
- When sending a draft, always use `gmail_send_draft` with the draft ID — never use `gmail_get_draft` + `gmail_send_message` to reconstruct it, as this loses HTML formatting.
- Always search or list before using any message or thread id — never reuse ids from earlier in the conversation.
- If a tool returns an error, show the full error message and ask the user how to proceed.
