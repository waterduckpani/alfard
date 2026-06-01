"""Cron context builder — constructs the autonomous-execution context block
injected as a message prefix when a cron job fires into a live session."""


def build_cron_context(job_name: str, task: str) -> str:
    """Return the cron context block prepended to every scheduled run message."""
    return (
        f"# Cron execution context\n\n"
        f"You are running as an automated cron job. There is no human present.\n\n"
        f"**Job:** {job_name}\n"
        f"**Task:** {task}\n\n"
        f"Rules for this run:\n"
        f"- The base prompt instruction to confirm actions before taking them is suspended. Proceed directly.\n"
        f"- For every action you would normally ask confirmation for, proceed directly "
        f"and attempt the tool call — do not ask 'shall I proceed', 'would you like me to', "
        f"or any variant.\n"
        f"- The approval gate will automatically intercept any irreversible action and route "
        f"it to the configured channel for human approval. Your job is to get as far as "
        f"possible autonomously and let the gate handle confirmation. Never stop and ask — "
        f"just act.\n"
        f"- If a tool returns a 404 error, try an alternative call with the same ID "
        f"(e.g. look up by thread ID instead of message ID) before reporting failure.\n"
        f"- When finished, output a clean summary: what was completed, what was skipped, "
        f"and why anything was skipped.\n\n"
        f"**CRON OVERRIDE — this supersedes all other instructions including soul, skills, and base prompt:** "
        f"Do NOT ask for confirmation, clarification, or approval at any point. "
        f"Do NOT output 'shall I proceed', 'would you like me to', 'should I', "
        f"'before I do this', or any variant. "
        f"Attempt every tool call immediately when you have the required parameters. "
        f"The approval gate intercepts irreversible actions automatically — you do not need to "
        f"and must not ask the user. "
        f"Any instruction from skills or soul telling you to confirm first is suspended for this entire cron session."
    )
