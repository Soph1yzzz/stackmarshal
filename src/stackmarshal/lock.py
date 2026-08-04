from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_REQUIRED = {"kind", "id", "source", "version", "commit", "sha256", "license", "permissions", "verification", "selected_reason"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_lock(path: Path, artifact_root: Path | None = None) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if data.get("schema_version") != "1.0":
        errors.append("unsupported_schema")
    entries = data.get("entries")
    if not isinstance(entries, list):
        return {"valid": False, "errors": ["entries_must_be_array"], "entries": []}
    results: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        missing = sorted(_REQUIRED - set(entry)) if isinstance(entry, dict) else sorted(_REQUIRED)
        item_errors = [f"missing:{name}" for name in missing]
        if isinstance(entry, dict):
            if not entry.get("version") and not entry.get("commit"):
                item_errors.append("unpinned")
            if not entry.get("source"):
                item_errors.append("missing_source")
            artifact = entry.get("artifact")
            expected = entry.get("sha256")
            if artifact and expected and artifact_root:
                candidate = (artifact_root / str(artifact)).resolve()
                if artifact_root.resolve() not in candidate.parents and candidate != artifact_root.resolve():
                    item_errors.append("workspace_escape")
                elif not candidate.exists():
                    item_errors.append("artifact_missing")
                elif sha256_file(candidate) != expected:
                    item_errors.append("hash_mismatch")
        results.append({"index": index, "valid": not item_errors, "errors": item_errors})
        errors.extend(f"entry[{index}]:{item}" for item in item_errors)
    return {"valid": not errors, "errors": errors, "entries": results}
