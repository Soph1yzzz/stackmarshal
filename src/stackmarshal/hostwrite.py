from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import uuid
from typing import Any

from .integrity import ensure_signing_key_outside, sign_record, state_home, verify_record
from .state import now_iso, project_info
from .workspace_io import HostPlanWorkspaceWriter


class HostWriteError(RuntimeError):
    pass


PLAN_SCHEMA_VERSION = "1.0"


def _normalized_root_key(root: Path) -> str:
    normalized = str(root.resolve()).casefold().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _host_write_home(root: Path) -> Path:
    ensure_signing_key_outside(root)
    home = state_home().expanduser().resolve(strict=False) / "host-write"
    resolved_root = root.resolve()
    if home == resolved_root or resolved_root in home.parents:
        raise HostWriteError("Host-write pending state must be stored outside the project")
    return home


def pending_plan_path(root: Path) -> Path:
    return _host_write_home(root) / "pending" / f"{_normalized_root_key(root)}.json"


def receipt_path(root: Path, plan_id: str) -> Path:
    return _host_write_home(root) / "receipts" / f"{plan_id}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_signed_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HostWriteError(f"Could not read host-write record: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HostWriteError("Host-write record must be a JSON object")
    try:
        verify_record(data)
    except ValueError as exc:
        raise HostWriteError(f"Host-write integrity validation failed: {exc}") from exc
    return data


def load_pending_plan(root: Path) -> dict[str, Any] | None:
    path = pending_plan_path(root)
    if not path.exists():
        return None
    plan = _load_signed_json(path)
    _validate_plan_identity(root, plan)
    return plan


def require_no_pending_plan(root: Path) -> None:
    pending = load_pending_plan(root)
    if pending is None:
        return
    raise HostWriteError(
        "A host-write plan is still pending; apply it with the host file API and run "
        f"'stackmarshal --root {root} host-write ack --plan-id {pending.get('plan_id')}', "
        "or explicitly abort it."
    )


def create_pending_plan(
    root: Path,
    writer: HostPlanWorkspaceWriter,
    *,
    command: list[str],
    command_result: Any,
    command_exit_code: int,
) -> dict[str, Any] | None:
    operations = writer.mutations()
    if not operations:
        return None
    require_no_pending_plan(root)
    current_project = project_info(root)
    plan_id = uuid.uuid4().hex
    plan = sign_record(
        {
            "schema_version": PLAN_SCHEMA_VERSION,
            "record_type": "host_write_plan",
            "plan_id": plan_id,
            "created_at": now_iso(),
            "project_root": str(root.resolve()),
            "project_identity": current_project.identity_hash,
            "command": command,
            "command_exit_code": int(command_exit_code),
            "command_result": command_result,
            "required_directories": writer.required_directories(),
            "operations": operations,
        }
    )
    _atomic_write_json(pending_plan_path(root), plan)
    return plan


def _validate_plan_identity(root: Path, plan: dict[str, Any]) -> None:
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION or plan.get("record_type") != "host_write_plan":
        raise HostWriteError("Unsupported host-write plan schema")
    if plan.get("project_root") != str(root.resolve()):
        raise HostWriteError("Host-write plan belongs to a different workspace root")
    current_identity = project_info(root).identity_hash
    if plan.get("project_identity") != current_identity:
        raise HostWriteError("Workspace identity changed after host-write plan creation")
    if not isinstance(plan.get("plan_id"), str) or not plan["plan_id"]:
        raise HostWriteError("Host-write plan is missing plan_id")
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise HostWriteError("Host-write plan has no operations")
    seen: set[str] = set()
    for raw in operations:
        if not isinstance(raw, dict) or raw.get("operation") != "write_text":
            raise HostWriteError("Host-write plan contains an unsupported operation")
        relative = raw.get("path")
        content = raw.get("content")
        content_hash = raw.get("content_sha256")
        preimage = raw.get("expected_preimage")
        preimage_hash = raw.get("expected_preimage_sha256")
        if not isinstance(relative, str) or not isinstance(content, str) or not isinstance(content_hash, str):
            raise HostWriteError("Host-write plan contains an invalid text operation")
        _validate_relative_path(relative)
        if relative in seen:
            raise HostWriteError(f"Host-write plan contains duplicate target: {relative}")
        seen.add(relative)
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != content_hash:
            raise HostWriteError(f"Host-write content hash is inconsistent: {relative}")
        if preimage is None:
            if preimage_hash is not None:
                raise HostWriteError(f"Host-write absent preimage has a hash: {relative}")
        elif not isinstance(preimage, str) or not isinstance(preimage_hash, str):
            raise HostWriteError(f"Host-write preimage contract is invalid: {relative}")
        elif hashlib.sha256(preimage.encode("utf-8")).hexdigest() != preimage_hash:
            raise HostWriteError(f"Host-write preimage hash is inconsistent: {relative}")


def _validate_relative_path(relative: str) -> None:
    if not relative or "\\" in relative or ":" in relative:
        raise HostWriteError(f"Unsafe host-write target: {relative!r}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise HostWriteError(f"Unsafe host-write target: {relative!r}")
    if pure.as_posix() != relative:
        raise HostWriteError(f"Non-canonical host-write target: {relative!r}")


def _target(root: Path, relative: str) -> Path:
    _validate_relative_path(relative)
    candidate = root / Path(relative)
    resolved_root = root.resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HostWriteError(f"Host-write target escapes workspace: {relative}") from exc
    current = resolved_root
    for part in Path(relative).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise HostWriteError(f"Host-write ancestor may not be a symlink: {relative}")
        if current.exists():
            if not current.is_dir():
                raise HostWriteError(f"Host-write ancestor is not a directory: {relative}")
            resolved = current.resolve(strict=True)
            if resolved != resolved_root and resolved_root not in resolved.parents:
                raise HostWriteError(f"Host-write ancestor escapes workspace: {relative}")
    if candidate.is_symlink():
        raise HostWriteError(f"Host-write target may not be a symlink: {relative}")
    return candidate


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_pending_plan(root: Path, plan_id: str) -> dict[str, Any]:
    plan = load_pending_plan(root)
    if plan is None:
        raise HostWriteError("No host-write plan is pending")
    if plan.get("plan_id") != plan_id:
        raise HostWriteError("Pending host-write plan id does not match")
    errors: list[str] = []
    for raw in plan["operations"]:
        if not isinstance(raw, dict) or raw.get("operation") != "write_text":
            errors.append("unsupported_operation")
            continue
        relative = raw.get("path")
        if not isinstance(relative, str):
            errors.append("invalid_path")
            continue
        try:
            target = _target(root, relative)
        except HostWriteError as exc:
            errors.append(str(exc))
            continue
        expected = raw.get("expected_preimage_sha256")
        if expected is None:
            if target.exists() or target.is_symlink():
                errors.append(f"preimage_expected_absent:{relative}")
        elif not isinstance(expected, str):
            errors.append(f"invalid_preimage_hash:{relative}")
        elif target.is_symlink() or not target.is_file():
            errors.append(f"preimage_missing_or_unsafe:{relative}")
        elif _sha256(target) != expected:
            errors.append(f"preimage_hash_mismatch:{relative}")
    return {
        "ready_to_apply": not errors,
        "plan_id": plan_id,
        "project_root": str(root.resolve()),
        "errors": errors,
        "operations": plan["operations"],
    }


def acknowledge_pending_plan(root: Path, plan_id: str) -> dict[str, Any]:
    plan = load_pending_plan(root)
    if plan is None:
        raise HostWriteError("No host-write plan is pending")
    if plan.get("plan_id") != plan_id:
        raise HostWriteError("Pending host-write plan id does not match")
    errors: list[str] = []
    verified: list[dict[str, str]] = []
    for raw in plan["operations"]:
        if not isinstance(raw, dict) or raw.get("operation") != "write_text":
            errors.append("unsupported_operation")
            continue
        relative = raw.get("path")
        expected = raw.get("content_sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            errors.append("invalid_operation")
            continue
        try:
            target = _target(root, relative)
        except HostWriteError as exc:
            errors.append(str(exc))
            continue
        if target.is_symlink() or not target.is_file():
            errors.append(f"postimage_missing_or_unsafe:{relative}")
            continue
        actual = _sha256(target)
        if actual != expected:
            errors.append(f"postimage_hash_mismatch:{relative}")
            continue
        verified.append({"path": relative, "sha256": actual})
    if errors:
        return {"acknowledged": False, "plan_id": plan_id, "errors": errors}
    receipt = sign_record(
        {
            "schema_version": PLAN_SCHEMA_VERSION,
            "record_type": "host_write_receipt",
            "plan_id": plan_id,
            "acknowledged_at": now_iso(),
            "project_root": str(root.resolve()),
            "project_identity": project_info(root).identity_hash,
            "verified_postimages": verified,
        }
    )
    destination = receipt_path(root, plan_id)
    _atomic_write_json(destination, receipt)
    pending_plan_path(root).unlink()
    return {
        "acknowledged": True,
        "plan_id": plan_id,
        "receipt": str(destination),
        "verified_postimages": verified,
    }


def abort_pending_plan(root: Path, plan_id: str, reason: str) -> dict[str, Any]:
    plan = load_pending_plan(root)
    if plan is None:
        raise HostWriteError("No host-write plan is pending")
    if plan.get("plan_id") != plan_id:
        raise HostWriteError("Pending host-write plan id does not match")
    pending_plan_path(root).unlink()
    return {"aborted": True, "plan_id": plan_id, "reason": reason}


def pending_status(root: Path) -> dict[str, Any]:
    plan = load_pending_plan(root)
    if plan is None:
        return {"pending": False}
    return {
        "pending": True,
        "plan_id": plan["plan_id"],
        "created_at": plan.get("created_at"),
        "operation_count": len(plan.get("operations", [])),
        "command": plan.get("command"),
    }
