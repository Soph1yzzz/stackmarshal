from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any

from .integrity import ensure_signing_key_outside, sign_record, state_home, verify_record
from .models import RunState
from .state import (
    now_iso,
    portable_project_identity,
    project_info,
    terminal_workspace_fingerprint,
    worktree_fingerprint,
)


class RelocationError(RuntimeError):
    pass


RELOCATION_SCHEMA_VERSION = "1.0"


def _relocation_home(root: Path) -> Path:
    ensure_signing_key_outside(root)
    home = state_home().expanduser().resolve(strict=False) / "relocations"
    resolved_root = root.resolve()
    if home == resolved_root or resolved_root in home.parents:
        raise RelocationError("Relocation permits must be stored outside the project")
    return home


def relocation_permit_path(root: Path, permit_id: str) -> Path:
    if len(permit_id) != 32 or any(char not in "0123456789abcdef" for char in permit_id):
        raise RelocationError("Invalid relocation permit id")
    return _relocation_home(root) / "permits" / f"{permit_id}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare_relocation(root: Path, state: RunState, destination: Path) -> dict[str, Any]:
    source = root.resolve(strict=True)
    target = destination.expanduser().resolve(strict=False)
    if target == source:
        raise RelocationError("Relocation destination is the current workspace root")
    current = project_info(source)
    if state.project.identity_hash != current.identity_hash or Path(state.project.root).resolve() != source:
        raise RelocationError("Run project identity does not match the current workspace before relocation")
    permit_id = uuid.uuid4().hex
    permit = sign_record(
        {
            "schema_version": RELOCATION_SCHEMA_VERSION,
            "record_type": "workspace_relocation_permit",
            "permit_id": permit_id,
            "created_at": now_iso(),
            "run_id": state.run_id,
            "from_root": str(source),
            "to_root": str(target),
            "from_identity": current.identity_hash,
            "portable_project_identity": portable_project_identity(source),
            "workspace_fingerprint": terminal_workspace_fingerprint(source),
            "git_head": current.git_head,
            "dirty": current.dirty,
        }
    )
    _atomic_write_json(relocation_permit_path(source, permit_id), permit)
    return permit


def load_relocation_permit(root: Path, permit_id: str) -> dict[str, Any]:
    path = relocation_permit_path(root, permit_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RelocationError(f"Could not read relocation permit: {permit_id}") from exc
    if not isinstance(raw, dict):
        raise RelocationError("Relocation permit must be a JSON object")
    try:
        verify_record(raw)
    except ValueError as exc:
        raise RelocationError(f"Relocation permit integrity validation failed: {exc}") from exc
    if raw.get("schema_version") != RELOCATION_SCHEMA_VERSION or raw.get("record_type") != "workspace_relocation_permit":
        raise RelocationError("Unsupported relocation permit schema")
    if raw.get("permit_id") != permit_id:
        raise RelocationError("Relocation permit id mismatch")
    return raw


def migrate_checkpoint_for_relocation(
    root: Path,
    state: RunState,
    permit: dict[str, Any],
    checkpoint_path: Path,
) -> dict[str, Any] | None:
    if not checkpoint_path.exists():
        return None
    try:
        raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RelocationError("Could not read checkpoint during relocation") from exc
    if not isinstance(raw, dict):
        raise RelocationError("Checkpoint must be a JSON object during relocation")
    try:
        verify_record(raw)
    except ValueError as exc:
        raise RelocationError(f"Checkpoint integrity failed during relocation: {exc}") from exc
    if raw.get("run_id") != state.run_id:
        raise RelocationError("Checkpoint belongs to a different run during relocation")
    if raw.get("project_identity") != permit.get("from_identity"):
        raise RelocationError("Checkpoint project identity does not match relocation source")
    current_fingerprint = worktree_fingerprint(root)
    if raw.get("worktree_fingerprint") != current_fingerprint:
        raise RelocationError("Checkpoint worktree fingerprint changed during relocation")
    current = project_info(root)
    if current.git_head != raw.get("git_head") or current.dirty != bool(raw.get("dirty")):
        raise RelocationError("Checkpoint Git state changed during relocation")
    migrated = dict(raw)
    for field in ("integrity_algorithm", "integrity_key_id", "integrity_hmac_sha256"):
        migrated.pop(field, None)
    migrated["project_identity"] = current.identity_hash
    migrated["git_head"] = current.git_head
    migrated["dirty"] = current.dirty
    migrated["worktree_fingerprint"] = current_fingerprint
    return sign_record(migrated)


def accept_relocation(root: Path, state: RunState, permit: dict[str, Any]) -> dict[str, Any]:
    destination = root.resolve(strict=True)
    if permit.get("run_id") != state.run_id:
        raise RelocationError("Relocation permit belongs to a different run")
    if permit.get("to_root") != str(destination):
        raise RelocationError("Relocation permit targets a different destination root")
    if state.project.identity_hash != permit.get("from_identity"):
        raise RelocationError("Run state no longer matches the relocation source identity")
    if Path(state.project.root).resolve(strict=False) != Path(str(permit.get("from_root"))).resolve(strict=False):
        raise RelocationError("Run state source root does not match the relocation permit")
    current_fingerprint = terminal_workspace_fingerprint(destination)
    if current_fingerprint != permit.get("workspace_fingerprint"):
        raise RelocationError("Workspace fingerprint changed during relocation")
    if portable_project_identity(destination) != permit.get("portable_project_identity"):
        raise RelocationError(
            "Repository identity changed during relocation; accept the relocation before a separate repository bootstrap"
        )
    current = project_info(destination)
    if current.git_head != permit.get("git_head") or current.dirty != bool(permit.get("dirty")):
        raise RelocationError("Git state changed during relocation")
    migration = {
        "reason": "workspace_relocation",
        "permit_id": permit.get("permit_id"),
        "from_root": permit.get("from_root"),
        "to_root": str(destination),
        "from_identity": state.project.identity_hash,
        "to_identity": current.identity_hash,
        "workspace_fingerprint": current_fingerprint,
    }
    state.project = current
    state.updated_at = now_iso()
    return migration
