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
    registry = context.get("tool_registry")

    lines = [f"**Agent:** {agent_name}"]

    if registry:
        tools = registry.all_tools()
        mcp_tools = [t for t in tools if t.get("is_mcp")]
        native_tools = [t for t in tools if not t.get("is_mcp")]
        KNOWN_INTEGRATIONS = {
            "notion", "github", "slack", "linear",
            "gmail", "gdrive", "drive"
        }
        if mcp_tools:
            servers = sorted(set(
                t["name"].split(".")[0] for t in mcp_tools
                if "." in t["name"]
            ))
            gws_services = sorted(set(
                t["name"].split("_")[0] for t in mcp_tools
                if "." not in t["name"]
                and t["name"].split("_")[0] in KNOWN_INTEGRATIONS
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
    turns = [
        m for m in messages
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
    ]

    if len(turns) < 2:
        return "Nothing to remember yet — have a conversation first."

    # Ask LLM to extract a memorable fact
    summary_prompt = (
        "Extract the single most important fact or preference from "
        "this conversation worth remembering permanently.\n"
        "Write it as one clear sentence.\n"
        "Also provide 3-5 relevant tags as comma-separated keywords.\n"
        "Format your response exactly as:\n"
        "FACT: <the fact>\n"
        "TAGS: <tag1, tag2, tag3>\n\n"
        + "\n".join(
            f"{m['role'].upper()}: {str(m['content'])[:300]}"
            for m in turns[-10:]
            if isinstance(m.get("content"), str)
        )
    )

    try:
        response = llm.complete([
            {"role": "user", "content": summary_prompt}
        ])
        content = response.get("content", "").strip()
    except Exception as e:
        return f"Could not generate summary: {e}"

    # Parse FACT and TAGS
    fact = ""
    tags = []
    for line in content.split("\n"):
        if line.startswith("FACT:"):
            fact = line[5:].strip()
        elif line.startswith("TAGS:"):
            tags = [t.strip() for t in line[5:].split(",")]

    if not fact:
        return "Could not extract a memorable fact from this conversation."

    loader.memory_manager.store_fact(fact, tags)
    return f"Saved to memory:\n\n**{fact}**\nTags: {', '.join(tags)}"


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
    from alfard.commands.registry import _commands, register
    if _commands:
        return
    register("/help",     "List all available commands",           handle_help)
    register("/clear",    "Clear conversation context",            handle_clear)
    register("/status",   "Show agent, integrations, turn count",  handle_status)
    register("/skills",   "List active skills for this agent",     handle_skills)
    register("/remember", "Save this session to brain.md",         handle_remember)
    register("/reset",    "Wipe memory.md for this agent",         handle_reset)
    register("/model",    "Show current LLM provider and model",   handle_model)
