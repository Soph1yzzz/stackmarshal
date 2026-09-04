from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import stat
from typing import Any

from .constants import STATE_DIR
from .integrity import INTEGRITY_ALGORITHM


class MigrationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained(path: Path, root: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    if path.is_symlink():
        raise MigrationError(f"Legacy state path may not be a symlink: {path}")
    resolved = path.resolve(strict=True)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise MigrationError(f"Legacy state path escapes the project: {path}")
    return resolved


def _read_record(path: Path, project_root: Path) -> dict[str, Any]:
    _contained(path, project_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"Legacy state is unreadable: {path}") from exc
    if not isinstance(raw, dict):
        raise MigrationError(f"Legacy state must be a JSON object: {path}")
    return raw


def _is_unsigned_legacy(raw: dict[str, Any]) -> bool:
    algorithm = raw.get("integrity_algorithm")
    key_id = raw.get("integrity_key_id")
    signature = raw.get("integrity_hmac_sha256")
    if algorithm is None and key_id is None and signature is None:
        return True
    if algorithm != INTEGRITY_ALGORITHM or not isinstance(key_id, str) or not isinstance(signature, str):
        raise MigrationError("State has a partial or unsupported integrity envelope; refusing legacy migration")
    return False


def find_legacy_unsigned_state(root: Path) -> list[Path]:
    root = root.resolve(strict=True)
    state_root = root / STATE_DIR
    if not state_root.exists():
        return []
    _contained(state_root, root)
    legacy: list[Path] = []
    runs = state_root / "runs"
    if runs.exists():
        _contained(runs, root)
        for run_state in sorted(runs.glob("*/run.json")):
            raw = _read_record(run_state, root)
            if _is_unsigned_legacy(raw):
                legacy.append(run_state)
    task_graph = state_root / "project" / "task-graph.json"
    if task_graph.exists():
        raw = _read_record(task_graph, root)
        if _is_unsigned_legacy(raw):
            legacy.append(task_graph)
    return legacy


def _archive_file_manifest(base: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise MigrationError(f"Legacy archive source contains symlink: {path}")
        if not path.is_file():
            continue
        entries.append(
            {
                "path": path.relative_to(base).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    return entries


def _make_read_only(base: Path) -> None:
    for path in sorted(base.rglob("*"), reverse=True):
        if path.is_file():
            with suppress(OSError):
                path.chmod(stat.S_IREAD)
    with suppress(OSError):
        base.chmod(stat.S_IREAD | stat.S_IEXEC)


def migrate_legacy_state(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    root = root.resolve(strict=True)
    legacy = find_legacy_unsigned_state(root)
    if not legacy:
        return {"migrated": False, "legacy_paths": [], "archive": None, "reason": "no_legacy_unsigned_state"}

    state_root = root / STATE_DIR
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # Keep the archive under runs/ so the existing local/runtime ignore boundary
    # continues to cover migrated evidence without mutating project .gitignore.
    archive = state_root / "runs" / "_legacy_archive" / timestamp
    planned: list[tuple[Path, Path]] = []
    seen_run_dirs: set[Path] = set()

    for path in legacy:
        if path.name == "run.json" and path.parent.parent.name == "runs":
            source = path.parent
            if source in seen_run_dirs:
                continue
            seen_run_dirs.add(source)
            destination = archive / "runs" / source.name
            planned.append((source, destination))
        elif path.name == "task-graph.json":
            for name in ("task-graph.json", "task-graph.md"):
                source = path.parent / name
                if source.exists():
                    planned.append((source, archive / "project" / name))

    result = {
        "migrated": not dry_run,
        "dry_run": dry_run,
        "legacy_paths": [str(path.relative_to(root)) for path in legacy],
        "archive": str(archive.relative_to(root)),
        "moves": [
            {"source": str(source.relative_to(root)), "destination": str(destination.relative_to(root))}
            for source, destination in planned
        ],
    }
    if dry_run:
        return result

    archive.mkdir(parents=True, exist_ok=False)
    try:
        for source, destination in planned:
            _contained(source, root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        manifest_entries = _archive_file_manifest(archive)
        manifest = {
            "schema_version": 1,
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "reason": "legacy_unsigned_state_archived_without_trust_promotion",
            "files": manifest_entries,
        }
        manifest_path = archive / "archive-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["manifest"] = str(manifest_path.relative_to(root))
        _make_read_only(archive)
    except Exception:
        # Keep any partially moved evidence visible; never delete source or archive bytes during a failed migration.
        raise
    return result
