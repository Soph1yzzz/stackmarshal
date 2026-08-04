from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----", re.S),
]


def redact(text: str) -> str:
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def normalize_message(message: str) -> str:
    text = redact(message).casefold()
    text = re.sub(r"0x[0-9a-f]+", "<hex>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<num>", text)
    text = re.sub(r"[a-z]:\\[^\s]+|/(?:[^\s/]+/)+[^\s]+", "<path>", text)
    return re.sub(r"\s+", " ", text).strip()[:1000]


def fingerprint(record: dict[str, Any]) -> str:
    canonical = {
        "command_category": record.get("command_category", "unknown"),
        "error_category": record.get("error_category", "unknown"),
        "target": record.get("target", "unknown"),
        "normalized_message": normalize_message(str(record.get("message", ""))),
        "suspected_root_cause": normalize_message(str(record.get("suspected_root_cause", ""))),
        "environment": record.get("environment", {}),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def repeated(fingerprints: list[str], candidate: str, limit: int) -> bool:
    return sum(item == candidate for item in fingerprints) >= limit
