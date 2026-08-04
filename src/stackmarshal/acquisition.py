from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from .security import ensure_within_workspace, inspect_package_manifest


@dataclass(frozen=True, slots=True)
class AcquisitionReceipt:
    candidate_id: str
    source: str
    version: str | None
    commit: str | None
    sha256: str | None
    target: str
    files_created: tuple[str, ...]
    rollback: tuple[str, ...]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_candidate(candidate: dict[str, Any], manifest_text: str = "") -> dict[str, Any]:
    findings = inspect_package_manifest(manifest_text) if manifest_text else []
    pinned = bool(candidate.get("version") or candidate.get("commit"))
    source = str(candidate.get("source", ""))
    risks: list[str] = list(findings)
    if not pinned:
        risks.append("cannot_pin_version")
    if not source.startswith(("https://", "file://")):
        risks.append("invalid_source")
    if candidate.get("license") in (None, "", "UNKNOWN"):
        risks.append("no_license")
    return {"safe": not risks, "risks": sorted(set(risks)), "pinned": pinned}


def install_project_file(
    *,
    candidate_id: str,
    source_file: Path,
    target_root: Path,
    relative_target: Path,
    source: str,
    version: str | None,
    commit: str | None,
) -> AcquisitionReceipt:
    target = ensure_within_workspace(target_root, target_root / relative_target)
    if target == target_root.resolve():
        raise ValueError("Acquisition target cannot be the workspace root")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Refusing to overwrite existing file: {target}")
    if source_file.is_symlink() or not source_file.is_file():
        raise ValueError(f"Acquisition source must be a regular non-symlink file: {source_file}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return AcquisitionReceipt(
        candidate_id=candidate_id,
        source=source,
        version=version,
        commit=commit,
        sha256=digest,
        target=str(target),
        files_created=(str(target),),
        rollback=(str(target),),
        timestamp=datetime.now(UTC).isoformat(),
    )


def _recorded_path(target_root: Path, value: str) -> Path:
    root = target_root.resolve()
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raw = root / raw
    # Normalize `..` without following the final path if it is a symlink.
    candidate = Path(os.path.abspath(raw))
    if candidate == root:
        raise ValueError("Rollback may not target the workspace root")
    parent = candidate.parent.resolve()
    if parent != root and root not in parent.parents:
        raise ValueError(f"Workspace escape rejected: {value}")
    return candidate


def rollback(receipt: AcquisitionReceipt, target_root: Path) -> None:
    created = {_recorded_path(target_root, value) for value in receipt.files_created}
    for value in reversed(receipt.rollback):
        path = _recorded_path(target_root, value)
        if path not in created:
            raise ValueError(f"Rollback entry was not created by this receipt: {value}")
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            raise ValueError(f"Rollback refuses recursive directory deletion: {path}")


def save_receipt(receipt: AcquisitionReceipt, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
