from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
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
    *, candidate_id: str, source_file: Path, target_root: Path, relative_target: Path,
    source: str, version: str | None, commit: str | None,
) -> AcquisitionReceipt:
    target = ensure_within_workspace(target_root, target_root / relative_target)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {target}")
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


def rollback(receipt: AcquisitionReceipt, target_root: Path) -> None:
    for value in reversed(receipt.rollback):
        path = ensure_within_workspace(target_root, Path(value))
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def save_receipt(receipt: AcquisitionReceipt, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
