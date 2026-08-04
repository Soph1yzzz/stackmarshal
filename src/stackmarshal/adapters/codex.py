from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any


class CodexAdapter:
    """Read-only environment discovery for Codex v1.

    Task execution remains under the host Codex agent; this adapter deliberately
    does not evaluate arbitrary commands from discovered content.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def detect_environment(self) -> dict[str, Any]:
        return {
            "os": platform.system(),
            "os_version": platform.version(),
            "python": platform.python_version(),
            "git": shutil.which("git"),
            "gh": shutil.which("gh"),
            "codex_home": str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))),
            "workspace": str(self.root),
            "git_dirty": self._git_dirty(),
        }

    def list_native_capabilities(self) -> list[dict[str, Any]]:
        home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        skills: list[dict[str, Any]] = []
        for base in (home / "skills", Path.home() / ".agents" / "skills"):
            if not base.exists():
                continue
            for skill in sorted(base.glob("*/SKILL.md")):
                skills.append({"kind": "skill", "id": skill.parent.name, "path": str(skill)})
        return skills

    def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "delegated_to_host",
            "task_id": task.get("id"),
            "note": "StackMarshal Core never executes arbitrary discovered instructions.",
        }

    def verify(self, scope: Path) -> dict[str, Any]:
        return {"scope": str(scope.resolve()), "exists": scope.exists()}

    def _git_dirty(self) -> bool | None:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.root,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return bool(result.stdout.strip())

    def write_audit(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "environment": self.detect_environment(),
            "native_capabilities": self.list_native_capabilities(),
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
