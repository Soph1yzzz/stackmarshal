from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from .constants import SCHEMA_VERSION, Status
from .models import RunState
from .state import project_info


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
    metadata: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": state.run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "project_identity": state.project.identity_hash,
        "git_head": state.project.git_head,
        "dirty": state.project.dirty,
        "mode": state.mode.value,
        "status": state.status.value,
        "current_phase": state.phase.value,
        "budget_used": state.budget.used,
        "budget_remaining": state.budget.remaining(),
        "completed": completed_items,
        "do_not_repeat": do_not_repeat_items,
        "next_action": next_action,
        "files_changed": files_changed or [],
        "tests_run": tests_run or [],
        "stop_reason": state.stop_reason,
        "resume_command": "stackmarshal resume inspect",
    }
    canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    metadata["integrity_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    json_path = output_dir / "checkpoint.json"
    markdown_path = output_dir / "checkpoint.md"
    json_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown = f"""# StackMarshal Checkpoint

- Run: `{state.run_id}`
- Status: `{state.status.value}`
- Project: `{state.project.root}`
- Git HEAD: `{state.project.git_head or 'none'}`
- Mode: `{state.mode.value}`
- Current phase: `{state.phase.value}`

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
stackmarshal resume inspect
```
"""
    markdown_path.write_text(markdown, encoding="utf-8")
    return json_path, markdown_path


def inspect_checkpoint(path: Path, project_root: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported checkpoint schema: {data.get('schema_version')}")
    integrity = data.pop("integrity_sha256", None)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if integrity != hashlib.sha256(canonical.encode()).hexdigest():
        raise ValueError("Checkpoint integrity mismatch")
    current = project_info(project_root)
    if data.get("project_identity") != current.identity_hash:
        raise ValueError("Checkpoint project identity mismatch")
    if data.get("git_head") and current.git_head != data.get("git_head"):
        data.setdefault("warnings", []).append("Git HEAD changed since checkpoint")
    if bool(data.get("dirty")) != current.dirty:
        data.setdefault("warnings", []).append("Git dirty state changed since checkpoint")
    if data.get("status") == Status.COMPLETE.value:
        data.setdefault("warnings", []).append("Run is already complete")
    data["integrity_sha256"] = integrity
    return dict(data)
