from __future__ import annotations

from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import uuid
from typing import Any

from .integrity import ensure_signing_key_outside, sign_record, state_home, verify_record
from .state import now_iso, project_info
from .workspace_io import HostPlanWorkspaceWriter


class HostWriteError(RuntimeError):
    pass


PLAN_SCHEMA_VERSION = "1.1"
SUPPORTED_PLAN_SCHEMA_VERSIONS = {"1.0", PLAN_SCHEMA_VERSION}


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


def _blob_path(root: Path, digest: str) -> Path:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise HostWriteError("Invalid host-write blob digest")
    return _host_write_home(root) / "blobs" / f"{digest}.txt"


def _store_recovery_blobs(root: Path, writer: HostPlanWorkspaceWriter) -> None:
    for _relative, preimage in writer.recovery_preimages().items():
        payload = preimage.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        destination = _blob_path(root, digest)
        if destination.exists():
            if destination.read_bytes() != payload:
                raise HostWriteError("Host-write recovery blob hash collision or corruption")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(payload)
        temporary.replace(destination)


def _load_recovery_blob(root: Path, digest: str) -> str:
    path = _blob_path(root, digest)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise HostWriteError(f"Host-write recovery blob is unavailable: {digest}") from exc
    if hashlib.sha256(payload).hexdigest() != digest:
        raise HostWriteError(f"Host-write recovery blob failed hash validation: {digest}")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HostWriteError(f"Host-write recovery blob is not UTF-8 text: {digest}") from exc


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _create_pending_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    """Create the single pending slot without any replace/overwrite race."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise HostWriteError("A host-write plan became pending concurrently; the new plan was not stored") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        with suppress(OSError):
            path.unlink()
        raise


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
    _store_recovery_blobs(root, writer)
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
    _create_pending_json_exclusive(pending_plan_path(root), plan)
    return plan


def _validate_plan_identity(root: Path, plan: dict[str, Any]) -> None:
    if plan.get("schema_version") not in SUPPORTED_PLAN_SCHEMA_VERSIONS or plan.get("record_type") != "host_write_plan":
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
        if not isinstance(raw, dict):
            raise HostWriteError("Host-write plan contains an unsupported operation")
        operation = raw.get("operation")
        relative = raw.get("path")
        content_hash = raw.get("content_sha256")
        preimage_hash = raw.get("expected_preimage_sha256")
        if not isinstance(relative, str) or not isinstance(content_hash, str):
            raise HostWriteError("Host-write plan contains an invalid text operation")
        _validate_relative_path(relative)
        if relative in seen:
            raise HostWriteError(f"Host-write plan contains duplicate target: {relative}")
        seen.add(relative)
        if operation == "write_text":
            content = raw.get("content")
            preimage = raw.get("expected_preimage")
            if not isinstance(content, str):
                raise HostWriteError("Host-write plan contains an invalid text operation")
            if hashlib.sha256(content.encode("utf-8")).hexdigest() != content_hash:
                raise HostWriteError(f"Host-write content hash is inconsistent: {relative}")
            if preimage is None:
                if preimage_hash is not None:
                    raise HostWriteError(f"Host-write absent preimage has a hash: {relative}")
            elif not isinstance(preimage, str) or not isinstance(preimage_hash, str):
                raise HostWriteError(f"Host-write preimage contract is invalid: {relative}")
            elif hashlib.sha256(preimage.encode("utf-8")).hexdigest() != preimage_hash:
                raise HostWriteError(f"Host-write preimage hash is inconsistent: {relative}")
            continue
        if operation == "append_text":
            append_content = raw.get("append_content")
            append_hash = raw.get("append_sha256")
            preimage_size = raw.get("expected_preimage_size")
            expected_tail = raw.get("expected_tail")
            blob_hash = raw.get("preimage_blob_sha256")
            if not isinstance(append_content, str) or not isinstance(append_hash, str) or not isinstance(preimage_size, int):
                raise HostWriteError("Host-write plan contains an invalid append operation")
            if hashlib.sha256(append_content.encode("utf-8")).hexdigest() != append_hash:
                raise HostWriteError(f"Host-write append hash is inconsistent: {relative}")
            if preimage_hash is None:
                if preimage_size != 0 or blob_hash is not None or expected_tail is not None:
                    raise HostWriteError(f"Host-write absent append preimage is inconsistent: {relative}")
                if hashlib.sha256(append_content.encode("utf-8")).hexdigest() != content_hash:
                    raise HostWriteError(f"Host-write append postimage hash is inconsistent: {relative}")
            else:
                if not isinstance(preimage_hash, str) or blob_hash != preimage_hash:
                    raise HostWriteError(f"Host-write append preimage contract is invalid: {relative}")
                preimage = _load_recovery_blob(root, preimage_hash)
                if len(preimage.encode("utf-8")) != preimage_size:
                    raise HostWriteError(f"Host-write append preimage size is inconsistent: {relative}")
                if not isinstance(expected_tail, str) or not preimage.endswith(expected_tail) or len(expected_tail) > 512:
                    raise HostWriteError(f"Host-write append tail contract is invalid: {relative}")
                if hashlib.sha256((preimage + append_content).encode("utf-8")).hexdigest() != content_hash:
                    raise HostWriteError(f"Host-write append postimage hash is inconsistent: {relative}")
            continue
        raise HostWriteError("Host-write plan contains an unsupported operation")


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
        if not isinstance(raw, dict) or raw.get("operation") not in {"write_text", "append_text"}:
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
        if not isinstance(raw, dict) or raw.get("operation") not in {"write_text", "append_text"}:
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


def recover_pending_plan(root: Path, plan_id: str, relative_path: str | None = None) -> dict[str, Any]:
    plan = load_pending_plan(root)
    if plan is None:
        raise HostWriteError("No host-write plan is pending")
    if plan.get("plan_id") != plan_id:
        raise HostWriteError("Pending host-write plan id does not match")
    recovery: list[dict[str, Any]] = []
    for raw in plan["operations"]:
        if not isinstance(raw, dict):
            continue
        relative = raw.get("path")
        if not isinstance(relative, str) or (relative_path is not None and relative != relative_path):
            continue
        _validate_relative_path(relative)
        expected = raw.get("expected_preimage_sha256")
        if expected is None:
            recovery.append({"path": relative, "expected_absent": True, "content": None, "sha256": None})
            continue
        if raw.get("operation") == "write_text":
            content = raw.get("expected_preimage")
            if not isinstance(content, str):
                raise HostWriteError(f"Pending plan has no recoverable preimage: {relative}")
        elif raw.get("operation") == "append_text":
            content = _load_recovery_blob(root, str(expected))
        else:
            raise HostWriteError("Host-write plan contains an unsupported recovery operation")
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != expected:
            raise HostWriteError(f"Recovered preimage hash does not match signed plan: {relative}")
        recovery.append({"path": relative, "expected_absent": False, "content": content, "sha256": expected})
    if relative_path is not None and not recovery:
        raise HostWriteError(f"Pending plan does not target requested recovery path: {relative_path}")
    return {
        "recoverable": True,
        "plan_id": plan_id,
        "project_root": str(root.resolve()),
        "operations": recovery,
        "next_action": "Restore these signed preimages only through the host file API, then rerun host-write check.",
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
