from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from .constants import SCHEMA_VERSION, Status
from .integrity import (
    INTEGRITY_ALGORITHM,
    ensure_signing_key_outside,
    sign_record,
    signing_key_path,
    verify_record,
)
from .models import RunState
from .state import project_info, worktree_fingerprint


def checkpoint_key_path() -> Path:
    """Backward-compatible alias for the shared StackMarshal signing key path."""

    return signing_key_path()


def create_checkpoint(
    state: RunState,
    output_dir: Path,
    *,
    next_action: str,
    completed: list[str] | None = None,
    do_not_repeat: list[str] | None = None,
    files_changed: list[str] | None = None,
    tests_run: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    completed_items = completed or state.completed_phases
    do_not_repeat_items = do_not_repeat or []
    project_root = Path(state.project.root)
    current_project = project_info(project_root)
    ensure_signing_key_outside(project_root)
    metadata = sign_record(
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": state.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "project_identity": current_project.identity_hash,
            "git_head": current_project.git_head,
            "dirty": current_project.dirty,
            "worktree_fingerprint": worktree_fingerprint(project_root),
            "mode": state.mode.value,
            "status": state.status.value,
            "current_phase": state.phase.value,
            "resume_phase": state.progress.get("resume_phase"),
            "budget_used": state.budget.used,
            "budget_remaining": state.budget.remaining(),
            "completed": completed_items,
            "do_not_repeat": do_not_repeat_items,
            "next_action": next_action,
            "files_changed": files_changed or [],
            "tests_run": tests_run or [],
            "stop_reason": state.stop_reason,
            "resume_command": f"stackmarshal resume {state.run_id}",
        }
    )
    json_path = output_dir / "checkpoint.json"
    markdown_path = output_dir / "checkpoint.md"
    json_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    markdown = f"""# StackMarshal Checkpoint

- Run: `{state.run_id}`
- Status: `{state.status.value}`
- Project: `{state.project.root}`
- Git HEAD: `{current_project.git_head or 'none'}`
- Mode: `{state.mode.value}`
- Current phase: `{state.phase.value}`
- Integrity: `{INTEGRITY_ALGORITHM}` / key `{metadata['integrity_key_id']}`

## Stop reason

{json.dumps(state.stop_reason, ensure_ascii=False, indent=2) if state.stop_reason else 'None'}

## Completed

{chr(10).join(f'- {item}' for item in completed_items) or '- None'}

## Do not repeat

{chr(10).join(f'- {item}' for item in do_not_repeat_items) or '- None'}

## Next single action

{next_action}

## Resume

```text
stackmarshal resume {state.run_id}
```
"""
    markdown_path.write_text(markdown, encoding="utf-8")
    return json_path, markdown_path


def inspect_checkpoint(path: Path, project_root: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Checkpoint must be a JSON object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported checkpoint schema: {data.get('schema_version')}")
    ensure_signing_key_outside(project_root)
    verify_record(data)
    current = project_info(project_root)
    if data.get("project_identity") != current.identity_hash:
        raise ValueError("Checkpoint project identity mismatch")
    current_fingerprint = worktree_fingerprint(project_root)
    if data.get("worktree_fingerprint") != current_fingerprint:
        raise ValueError("Checkpoint worktree fingerprint mismatch")
    if data.get("git_head") and current.git_head != data.get("git_head"):
        raise ValueError("Checkpoint Git HEAD mismatch")
    if bool(data.get("dirty")) != current.dirty:
        raise ValueError("Checkpoint dirty-state mismatch")
    if data.get("status") == Status.COMPLETE.value:
        data.setdefault("warnings", []).append("Run is already complete")
    return dict(data)
