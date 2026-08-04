from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from typing import Any

from .constants import SCHEMA_VERSION, Status
from .models import RunState
from .state import project_info

_INTEGRITY_ALGORITHM = "hmac-sha256-v1"
_KEY_BYTES = 32


def _state_home() -> Path:
    configured = os.environ.get("STACKMARSHAL_STATE_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".stackmarshal"


def checkpoint_key_path() -> Path:
    configured = os.environ.get("STACKMARSHAL_CHECKPOINT_KEY_FILE")
    return Path(configured).expanduser() if configured else _state_home() / "checkpoint-signing.key"


def _load_checkpoint_key(*, create: bool) -> bytes:
    path = checkpoint_key_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if create and not path.exists():
        key = secrets.token_bytes(_KEY_BYTES)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(key)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Checkpoint signing key is missing or unsafe: {path}")
    key = path.read_bytes()
    if len(key) != _KEY_BYTES:
        raise ValueError(f"Checkpoint signing key has invalid length: {path}")
    try:
        path.chmod(0o600)
        path.parent.chmod(0o700)
    except OSError:
        # Windows ACLs are not represented fully by POSIX mode bits.
        pass
    return key


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def _canonical_checkpoint(data: dict[str, Any]) -> bytes:
    unsigned = {
        key: value
        for key, value in data.items()
        if key not in {"integrity_hmac_sha256", "warnings"}
    }
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sign_checkpoint(data: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, _canonical_checkpoint(data), hashlib.sha256).hexdigest()


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
    key = _load_checkpoint_key(create=True)
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
        "integrity_algorithm": _INTEGRITY_ALGORITHM,
        "integrity_key_id": _key_id(key),
    }
    metadata["integrity_hmac_sha256"] = _sign_checkpoint(metadata, key)
    json_path = output_dir / "checkpoint.json"
    markdown_path = output_dir / "checkpoint.md"
    json_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    markdown = f"""# StackMarshal Checkpoint

- Run: `{state.run_id}`
- Status: `{state.status.value}`
- Project: `{state.project.root}`
- Git HEAD: `{state.project.git_head or 'none'}`
- Mode: `{state.mode.value}`
- Current phase: `{state.phase.value}`
- Integrity: `{_INTEGRITY_ALGORITHM}` / key `{_key_id(key)}`

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
    if not isinstance(data, dict):
        raise ValueError("Checkpoint must be a JSON object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported checkpoint schema: {data.get('schema_version')}")
    if data.get("integrity_algorithm") != _INTEGRITY_ALGORITHM:
        raise ValueError("Unsupported or missing checkpoint integrity algorithm")
    supplied = data.get("integrity_hmac_sha256")
    if not isinstance(supplied, str):
        raise ValueError("Checkpoint signature is missing")
    key = _load_checkpoint_key(create=False)
    if data.get("integrity_key_id") != _key_id(key):
        raise ValueError("Checkpoint was signed by a different StackMarshal key")
    expected = _sign_checkpoint(data, key)
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("Checkpoint signature mismatch")
    current = project_info(project_root)
    if data.get("project_identity") != current.identity_hash:
        raise ValueError("Checkpoint project identity mismatch")
    if data.get("git_head") and current.git_head != data.get("git_head"):
        data.setdefault("warnings", []).append("Git HEAD changed since checkpoint")
    if bool(data.get("dirty")) != current.dirty:
        data.setdefault("warnings", []).append("Git dirty state changed since checkpoint")
    if data.get("status") == Status.COMPLETE.value:
        data.setdefault("warnings", []).append("Run is already complete")
    return dict(data)
