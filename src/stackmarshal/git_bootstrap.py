"""Early repository ownership check and conservative Git bootstrap."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        # Inherited GIT_DIR/WORK_TREE/CONFIG overrides may redirect a supposedly
        # local bootstrap to another repository. Never inherit Git control state.
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        return subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20, check=False, env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"Git is unavailable or failed: {exc}") from exc


def inspect_git(root: Path) -> dict[str, Any]:
    """Return repository ownership, not merely whether an ancestor contains Git."""

    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Workspace is not a directory: {root}")
    marker = root / ".git"
    if marker.is_symlink():
        raise ValueError("Workspace .git marker is a symlink")
    probe = _git(root, "rev-parse", "--show-toplevel")
    if probe.returncode != 0:
        if marker.exists():
            raise ValueError(f"Git metadata exists but repository inspection failed: {probe.stderr.strip()}")
        # A missing Git executable is not equivalent to a repository-free workspace.
        if probe.returncode != 128 or "not a git repository" not in probe.stderr.casefold():
            raise ValueError(f"Git repository inspection failed: {probe.stderr.strip()}")
        return {"status": "not_repository", "root": str(root), "git_head": None}
    top = Path(probe.stdout.strip()).resolve()
    if top != root:
        return {"status": "ancestor_repository_only", "root": str(root), "ancestor": str(top), "git_head": None}
    head = _git(root, "rev-parse", "--verify", "HEAD")
    return {
        "status": "ready_repository" if head.returncode == 0 else "unborn_repository",
        "root": str(root), "git_head": head.stdout.strip() if head.returncode == 0 else None,
    }


def bootstrap_git(root: Path, *, allow_nested: bool = False) -> dict[str, Any]:
    """Initialize only an unowned workspace. Never add, commit, or alter user files."""

    before = inspect_git(root)
    if before["status"] in {"ready_repository", "unborn_repository"}:
        return {**before, "initialized": False}
    if before["status"] == "ancestor_repository_only" and not allow_nested:
        raise ValueError("Workspace belongs to an ancestor repository; nested Git bootstrap needs explicit approval")
    root = root.resolve(strict=True)
    marker = root / ".git"
    if marker.exists() or marker.is_symlink():
        raise ValueError("Refusing Git bootstrap over existing .git metadata")
    result = _git(root, "init", "--template=")
    if result.returncode != 0:
        raise ValueError(f"Git initialization failed: {result.stderr.strip()}")
    after = inspect_git(root)
    if after["status"] != "unborn_repository":
        raise ValueError("Unexpected repository identity after Git initialization")
    return {**after, "initialized": True, "previous_status": before["status"], "initial_commit_created": False}
