# Memory skill

## When to write memory
- User states a preference, fact about themselves, or working style → preference or fact
- A mistake is made and corrected → mistake (always write this)
- User states a goal or ongoing project → goal
- A decision is reached → decision
- A person is mentioned with context → person
- A repeatable process is established → procedure
- Project status changes → project_state

## How to write memory
Call the memory write tool with: type, content, source=agent_inferred.
For user_explicit (/remember command): source=user_explicit.
Write one entry per distinct piece of information. Do not batch.

## Reading memory
- Call recall_memory when the user references something not in current context
- Call it before answering questions about past decisions, projects, or people
- Do not call it on every message — only when context is genuinely missing

## Rules
- Never output a ╭─ remembered ─╮ block yourself. The system emits
  this automatically after a confirmed write. If you produce it as
  text, the write did not happen.
- Never tell the user "I'll remember that" without immediately calling
  the write tool in the same turn.
- Never fabricate memory content — only write what was explicitly said
  or clearly implied.
- On /new or context reset: your conversation history clears but
  brain.db persists. Do not re-ask for information already in memory.
