"""Slash command handlers — one function per command.
Each handler receives a context dict and returns a response string."""

from datetime import datetime


def handle_help(context: dict) -> str:
    from alfard.commands.registry import list_commands
    lines = ["**Available commands:**\n"]
    for cmd in list_commands():
        lines.append(f"  {cmd['name']} — {cmd['description']}")
    return "\n".join(lines)


def handle_clear(context: dict) -> str:
    memory = context.get("memory")
    if memory:
        memory.reset()
    return "Context cleared. Starting fresh."


def handle_status(context: dict) -> str:
    agent_name = context.get("agent_name", "unknown")
    turn_count = context.get("turn_count", 0)
    registry = context.get("tool_registry")

    lines = [f"**Agent:** {agent_name}"]
    lines.append(f"**Turns this session:** {turn_count}")

    if registry:
        tools = registry.all_tools()
        mcp_tools = [t for t in tools if t.get("is_mcp")]
        native_tools = [t for t in tools if not t.get("is_mcp")]
        if mcp_tools:
            servers = sorted(set(
                t["name"].split(".")[0] for t in mcp_tools
                if "." in t["name"]
            ))
            gws_tools = [t for t in mcp_tools if "." not in t["name"]]
            gws_services = sorted(set(
                t["name"].split("_")[0] for t in gws_tools
            ))
            all_services = servers + gws_services
            if all_services:
                lines.append(
                    f"**Integrations:** {', '.join(all_services)}"
                )
        if native_tools:
            lines.append(
                f"**Tools:** {len(native_tools)} native"
            )

    return "\n".join(lines)


def handle_skills(context: dict) -> str:
    loader = context.get("loader")
    if not loader:
        return "No agent loaded."
    skills = loader.get_agent_skills()
    if not skills:
        return "No skills active. Add one: alfard skill add <agent> <skill>"
    return "**Active skills:** " + ", ".join(skills)


def handle_remember(context: dict) -> str:
    memory = context.get("memory")
    loader = context.get("loader")
    llm = context.get("llm")

    if not memory or not loader or not llm:
        return "Cannot save memory — missing context."

    messages = memory.get_messages()
    # Only include user/assistant turns
    turns = [
        m for m in messages
        if m["role"] in ("user", "assistant") and m.get("content")
    ]

    if len(turns) < 2:
        return "Nothing to remember yet — have a conversation first."

    # Ask LLM to summarise
    summary_prompt = (
        "Summarise this conversation in 3-5 bullet points.\n"
        "Focus on: facts learned, decisions made, tasks completed.\n"
        "Be concise. Each bullet max 20 words.\n"
        "Format: • bullet point\n\n"
        + "\n".join(
            f"{m['role'].upper()}: {m['content'][:300]}"
            for m in turns[-20:]
        )
    )

    try:
        response = llm.complete([
            {"role": "user", "content": summary_prompt}
        ])
        summary = response.get("content", "").strip()
    except Exception as e:
        return f"Could not generate summary: {e}"

    if not summary:
        return "Could not generate a summary."

    loader.append_brain(summary)
    return f"Saved to memory:\n\n{summary}"


def handle_reset(context: dict) -> str:
    loader = context.get("loader")
    if not loader:
        return "No agent loaded."
    loader.save_memory("")
    return "Memory reset. Starting fresh next session."


def handle_model(context: dict) -> str:
    llm = context.get("llm")
    if not llm:
        return "No LLM loaded."
    return (
        f"**Provider:** {llm.provider_name}\n"
        f"**Model:** {llm.model}"
    )


# ── Registration ──────────────────────────────────────────

def register_all() -> None:
    """Register all built-in commands. Call once at startup."""
    from alfard.commands.registry import register
    register("/help",     "List all available commands",           handle_help)
    register("/clear",    "Clear conversation context",            handle_clear)
    register("/status",   "Show agent, integrations, turn count",  handle_status)
    register("/skills",   "List active skills for this agent",     handle_skills)
    register("/remember", "Save this session to brain.md",         handle_remember)
    register("/reset",    "Wipe memory.md for this agent",         handle_reset)
    register("/model",    "Show current LLM provider and model",   handle_model)
