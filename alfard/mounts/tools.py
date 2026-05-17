"""File tools — registered as native alfard tools when an agent
has declared mounts. All operations are path-validated."""

from pathlib import Path
from alfard.mounts.manager import MountManager, MountError
from alfard.tools.registry import ToolRegistry


def register_file_tools(registry: ToolRegistry,
                        mount_manager: MountManager) -> None:
    """Register file tools scoped to the agent's declared mounts."""

    def file_read(path: str) -> str:
        """Read a file's contents."""
        try:
            resolved = mount_manager.check_read(path)
            if not resolved.exists():
                return f"File not found: {path}"
            if not resolved.is_file():
                return f"Not a file: {path}"
            return resolved.read_text(encoding="utf-8")
        except MountError as e:
            return str(e)
        except Exception as e:
            return f"Error reading {path}: {e}"

    def file_write(path: str, content: str) -> str:
        """Write content to a file. Creates the file if it doesn't exist."""
        try:
            resolved = mount_manager.check_write(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return f"Written: {path} ({len(content)} chars)"
        except MountError as e:
            return str(e)
        except Exception as e:
            return f"Error writing {path}: {e}"

    def file_append(path: str, content: str) -> str:
        """Append content to a file."""
        try:
            resolved = mount_manager.check_write(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Appended to: {path} ({len(content)} chars)"
        except MountError as e:
            return str(e)
        except Exception as e:
            return f"Error appending to {path}: {e}"

    def file_list(path: str = ".") -> str:
        """List files and folders in a directory."""
        try:
            resolved = mount_manager.check_read(path)
            if not resolved.exists():
                return f"Directory not found: {path}"
            if not resolved.is_dir():
                return f"Not a directory: {path}"

            items = sorted(resolved.iterdir())
            lines = []
            for item in items:
                if item.is_dir():
                    lines.append(f"[dir]  {item.name}/")
                else:
                    size = item.stat().st_size
                    lines.append(f"[file] {item.name} ({size} bytes)")

            if not lines:
                return f"Empty directory: {path}"

            return f"{path}:\n" + "\n".join(lines)
        except MountError as e:
            return str(e)
        except Exception as e:
            return f"Error listing {path}: {e}"

    def file_exists(path: str) -> str:
        """Check if a file or directory exists."""
        try:
            resolved = mount_manager.check_read(path)
            if resolved.exists():
                kind = "directory" if resolved.is_dir() else "file"
                return f"Exists ({kind}): {path}"
            return f"Does not exist: {path}"
        except MountError as e:
            return str(e)

    def file_delete(path: str) -> str:
        """Delete a file. (Disabled for safety.)"""
        return (
            "File deletion is disabled in alfard for safety.\n"
            "Delete the file manually if needed."
        )

    def file_list_mounts() -> str:
        """List all folders this agent has access to."""
        mounts = mount_manager.list_mounts()
        if not mounts:
            return "No folders are mounted for this agent."
        lines = []
        for m in mounts:
            access = m.get("access", "readonly")
            lines.append(f"  {m['path']} ({access})")
        return "Mounted folders:\n" + "\n".join(lines)

    tools = [
        (
            "file_read",
            "Read the contents of a file in a declared mount.",
            file_read, True,
            {"type": "object", "properties": {
                "path": {"type": "string",
                         "description": "Path to the file to read"}
            }, "required": ["path"]}
        ),
        (
            "file_write",
            "Write content to a file in a declared mount. "
            "Creates the file if it does not exist.",
            file_write, False,
            {"type": "object", "properties": {
                "path": {"type": "string",
                         "description": "Path to the file to write"},
                "content": {"type": "string",
                            "description": "Content to write to the file"}
            }, "required": ["path", "content"]}
        ),
        (
            "file_append",
            "Append content to the end of a file in a declared mount.",
            file_append, False,
            {"type": "object", "properties": {
                "path": {"type": "string",
                         "description": "Path to the file to append to"},
                "content": {"type": "string",
                            "description": "Content to append"}
            }, "required": ["path", "content"]}
        ),
        (
            "file_list",
            "List files and folders in a directory in a declared mount.",
            file_list, True,
            {"type": "object", "properties": {
                "path": {"type": "string",
                         "description": "Path to the directory to list"}
            }, "required": ["path"]}
        ),
        (
            "file_exists",
            "Check if a file or directory exists in a declared mount.",
            file_exists, True,
            {"type": "object", "properties": {
                "path": {"type": "string",
                         "description": "Path to check"}
            }, "required": ["path"]}
        ),
        (
            "file_delete",
            "Delete a file (disabled for safety).",
            file_delete, False,
            {"type": "object", "properties": {
                "path": {"type": "string",
                         "description": "Path to delete"}
            }, "required": ["path"]}
        ),
        (
            "file_list_mounts",
            "List all folders this agent has access to.",
            file_list_mounts, True,
            {"type": "object", "properties": {}}
        ),
    ]

    for name, desc, fn, reversible, params in tools:
        try:
            registry.register(
                name, desc, fn, reversible, params, is_mcp=True
            )
        except ValueError:
            pass
