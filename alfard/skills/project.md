# Project skill

Track ongoing work, milestones, and status across conversations. Use this skill whenever the user discusses a project — active, planned, or stalled.

## When to use it
- User mentions a project by name, describes a goal with a timeline, or asks about progress
- User wants to capture a decision, milestone, or blockers
- User asks "where are we on X" or "what's left for Y"

## How to behave
- Store project status in memory with type=project_state so it survives context resets
- When asked for a status update, pull from memory first, then ask the user to fill gaps
- Distinguish clearly between what's done, what's in progress, and what's not started
- Surface blockers proactively — if a dependency is unresolved, flag it
- Keep entries lean: one sentence per milestone, not a paragraph

## Hard rules
- Never invent progress. If you don't know the current state, ask.
- Always write a memory entry when project status changes — do not rely on conversation history.
- One project_state entry per project. Update it in place rather than creating duplicates.
