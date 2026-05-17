"""Mount manager — loads declared folder mounts for an agent
and enforces path security on all file operations."""

import yaml
from pathlib import Path


class MountError(Exception):
    pass


class MountManager:
    """
    Loads mounts from agents/<agent>/mounts.yaml and enforces
    path security on all file operations.

    mounts.yaml format:
      mounts:
        - path: ~/Documents/work
          access: readwrite
        - path: ~/Desktop/Projects/Stocky
          access: readonly
    """

    def __init__(self, agent_dir: Path):
        self.agent_dir = agent_dir
        self.mounts: list[dict] = []
        self._load()

    def _load(self) -> None:
        mounts_path = self.agent_dir / "mounts.yaml"
        if not mounts_path.exists():
            return

        with open(mounts_path) as f:
            data = yaml.safe_load(f) or {}

        for entry in data.get("mounts", []):
            raw_path = entry.get("path", "")
            access = entry.get("access", "readonly")
            resolved = Path(raw_path).expanduser().resolve()

            if not resolved.exists():
                raise MountError(
                    f"Mount path does not exist: {raw_path}\n"
                    f"Create the folder first, then re-run alfard."
                )

            self.mounts.append({
                "path": resolved,
                "access": access,
                "raw": raw_path,
            })

    def has_mounts(self) -> bool:
        return len(self.mounts) > 0

    def _resolve(self, path: str) -> Path:
        """Resolve a path string to absolute Path."""
        return Path(path).expanduser().resolve()

    def _find_mount(self, resolved: Path) -> dict | None:
        """Find which mount contains this path, if any."""
        for mount in self.mounts:
            try:
                resolved.relative_to(mount["path"])
                return mount
            except ValueError:
                continue
        return None

    def check_read(self, path: str) -> Path:
        """
        Validate a path for reading.
        Returns resolved Path if allowed.
        Raises MountError if blocked.
        """
        resolved = self._resolve(path)
        mount = self._find_mount(resolved)

        if mount is None:
            raise MountError(
                f"Access denied: {path}\n"
                f"This path is not in any declared mount.\n"
                f"Add it with: alfard mount add <agent> {path}"
            )

        return resolved

    def check_write(self, path: str) -> Path:
        """
        Validate a path for writing.
        Returns resolved Path if allowed.
        Raises MountError if blocked.
        """
        resolved = self._resolve(path)
        mount = self._find_mount(resolved)

        if mount is None:
            raise MountError(
                f"Access denied: {path}\n"
                f"This path is not in any declared mount."
            )

        if mount["access"] == "readonly":
            raise MountError(
                f"Access denied: {path}\n"
                f"This mount is read-only: {mount['raw']}"
            )

        return resolved

    def list_mounts(self) -> list[dict]:
        return self.mounts
