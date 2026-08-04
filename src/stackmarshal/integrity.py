from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from typing import Any

INTEGRITY_ALGORITHM = "hmac-sha256-v1"
_SIGNATURE_FIELD = "integrity_hmac_sha256"
_KEY_BYTES = 32


def state_home() -> Path:
    configured = os.environ.get("STACKMARSHAL_STATE_HOME")
    path = Path(configured).expanduser() if configured else Path.home() / ".stackmarshal"
    if not path.is_absolute():
        raise ValueError("STACKMARSHAL_STATE_HOME must be an absolute path")
    return path


def signing_key_path() -> Path:
    configured = os.environ.get("STACKMARSHAL_SIGNING_KEY_FILE") or os.environ.get(
        "STACKMARSHAL_CHECKPOINT_KEY_FILE"
    )
    path = Path(configured).expanduser() if configured else state_home() / "integrity-signing.key"
    if not path.is_absolute():
        raise ValueError("StackMarshal signing key path must be absolute")
    return path


def ensure_signing_key_outside(root: Path) -> None:
    resolved_root = root.resolve()
    key = signing_key_path().resolve(strict=False)
    if key == resolved_root or resolved_root in key.parents:
        raise ValueError("StackMarshal signing key must be stored outside the project")


def load_signing_key(*, create: bool) -> bytes:
    path = signing_key_path()
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
        raise ValueError(f"StackMarshal signing key is missing or unsafe: {path}")
    key = path.read_bytes()
    if len(key) != _KEY_BYTES:
        raise ValueError(f"StackMarshal signing key has invalid length: {path}")
    try:
        path.chmod(0o600)
        path.parent.chmod(0o700)
    except OSError:
        # Windows ACLs are not represented fully by POSIX mode bits.
        pass
    return key


def key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def canonical_record(data: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in data.items() if key != _SIGNATURE_FIELD}
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sign_record(data: dict[str, Any]) -> dict[str, Any]:
    key = load_signing_key(create=True)
    signed = dict(data)
    signed["integrity_algorithm"] = INTEGRITY_ALGORITHM
    signed["integrity_key_id"] = key_id(key)
    signed[_SIGNATURE_FIELD] = hmac.new(
        key, canonical_record(signed), hashlib.sha256
    ).hexdigest()
    return signed


def verify_record(data: dict[str, Any]) -> None:
    if data.get("integrity_algorithm") != INTEGRITY_ALGORITHM:
        raise ValueError("Unsupported or missing integrity algorithm")
    supplied = data.get(_SIGNATURE_FIELD)
    if not isinstance(supplied, str):
        raise ValueError("Integrity signature is missing")
    key = load_signing_key(create=False)
    if data.get("integrity_key_id") != key_id(key):
        raise ValueError("Record was signed by a different StackMarshal key")
    expected = hmac.new(key, canonical_record(data), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("Integrity signature mismatch")
