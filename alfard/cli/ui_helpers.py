"""Shared Rich UI helpers used across multiple CLI commands."""

from rich.table import Table
from alfard.cli.theme import p, c
from alfard.cli.components import alfard_table


def render_integration_table(catalogue: dict, connected: set[str] | None = None) -> Table:
    """Build a styled table of available integrations with optional status column."""
    from alfard.integrations.catalogue import AUTH_APIKEY

    columns = [
        {"header": "name", "key": "name", "align": "left"},
        {"header": "description", "key": "description", "align": "left"},
        {"header": "auth", "key": "auth", "align": "left"},
    ]
    if connected is not None:
        columns.append({"header": "status", "key": "status", "align": "left"})

    rows = []
    for name, info in catalogue.items():
        auth_label = "api key" if info["auth"] == AUTH_APIKEY else "oauth"
        row: dict = {
            "name": name,
            "description": info["description"],
            "auth": auth_label,
        }
        if connected is not None:
            if name in connected:
                row["status"] = c("ok", "connected")
            else:
                row["status"] = c("fg_faint", "not connected")
        rows.append(row)

    return alfard_table(columns, rows)
