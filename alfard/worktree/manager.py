"""Worktree manager — creates isolated git worktrees so agent file operations never touch main."""

# Worktree isolation: agent file operations happen on a disposable branch.
# main is never touched. The human reviews the diff and decides what merges.

import pathlib
import tempfile

import git

WORKTREE_PREFIX = "agent"


class WorktreeManager:

    def __init__(self, repo_path: str | None = None) -> None:
        if repo_path is None:
            repo_path = str(pathlib.Path.cwd())

        try:
            self._repo = git.Repo(repo_path, search_parent_directories=True)
            self._enabled = True
        except git.InvalidGitRepositoryError:
            self._repo = None
            self._enabled = False

        self._active_worktrees: dict[str, str] = {}

    def create(self, task_id: str) -> str | None:
        if not self._enabled:
            return None

        branch_name = f"{WORKTREE_PREFIX}/{task_id}"
        worktree_path = tempfile.mkdtemp(prefix=f"alfard-{task_id}-")

        try:
            self._repo.git.worktree("add", worktree_path, "-b", branch_name)
            self._active_worktrees[task_id] = worktree_path
            return worktree_path
        except Exception as exc:
            print(f"[worktree] warning: could not create worktree for '{task_id}': {exc}")
            return None

    def diff(self, task_id: str) -> str | None:
        if task_id not in self._active_worktrees:
            return None

        branch_name = f"{WORKTREE_PREFIX}/{task_id}"
        try:
            return self._repo.git.diff("main", branch_name)
        except git.GitCommandError:
            pass
        try:
            return self._repo.git.diff("master", branch_name)
        except Exception:
            return None

    def remove(self, task_id: str) -> None:
        if task_id not in self._active_worktrees:
            return

        path = self._active_worktrees[task_id]
        branch_name = f"{WORKTREE_PREFIX}/{task_id}"

        try:
            self._repo.git.worktree("remove", "--force", path)
        except Exception as exc:
            print(f"[worktree] warning: could not remove worktree for '{task_id}': {exc}")

        try:
            self._repo.git.branch("-D", branch_name)
        except Exception as exc:
            print(f"[worktree] warning: could not delete branch '{branch_name}': {exc}")

        self._active_worktrees.pop(task_id, None)

    def list_active(self) -> list[str]:
        return list(self._active_worktrees.keys())
