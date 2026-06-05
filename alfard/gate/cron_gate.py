"""CRON_ALWAYS_GATE — tool names that must always be approved in cron context.

These tools are intercepted by a pre_tool_hook set on the orchestrator for
every cron run, regardless of the job's approval_gate setting.
"""

CRON_ALWAYS_GATE: set[str] = {
    # Gmail — mutations
    "label_message",
    "label_thread",
    "unlabel_message",
    "unlabel_thread",
    "create_label",
    "update_label",
    "delete_label",
    # Google Drive — writes
    "create_file",
    "copy_file",
    # General destructive / side-effecting
    "send_message",
    "post_message",
    "delete_file",
    "delete_message",
    "delete_thread",
    "create_pull_request",
    "push_code",
    "execute_code",
    "run_script",
}
