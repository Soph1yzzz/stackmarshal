#!/usr/bin/env python3
"""Dependency-free StackMarshal Skill fallback.

The packaged `stackmarshal` CLI is authoritative. This fallback keeps invocation,
scoring, fingerprints, budget checks, progress evaluation, and checkpoint creation
available when a Skill was installed directly from its GitHub directory.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

WEIGHTS = {
    "requirement_fit": 30,
    "maintenance_health": 15,
    "security_posture": 15,
    "architecture_quality": 10,
    "license_compatibility": 10,
    "platform_support": 10,
    "integration_cost": 5,
    "documentation": 5,
}
DISQUALIFIERS = {
    "no_license", "archived", "incompatible_platform", "critical_known_vulnerability",
    "unapproved_secret_requirement", "suspicious_install_hook", "unreviewable_binary",
    "cannot_pin_version", "excessive_permissions",
}


def emit(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def invocation(text: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    exact = "$stackmarshal" in normalized or "stackmarshal" in normalized
    anti = any(re.search(pattern, normalized) for pattern in (
        r"stackmarshal\s*(とは|って何|について|に似た)",
        r"stackmarshal.{0,24}(readme|表記|名前).{0,16}(直|修正|編集)",
        r"(what is|explain|compare).{0,24}stackmarshal",
    ))
    markers = (
        "を使", "で実装", "で作", "で調べ", "で準備", "で続", "use stackmarshal",
        "with stackmarshal", "使用 stackmarshal", "用 stackmarshal", "stackmarshal로",
        "utilise stackmarshal", "utilize stackmarshal", "$stackmarshal",
    )
    triggered = exact and not anti and any(item in normalized for item in markers)
    mode = None
    if triggered:
        if any(item in normalized for item in ("resume", "続きから", "再開")):
            mode = "resume"
        elif any(item in normalized for item in ("prepare", "準備", "計画まで")):
            mode = "prepare"
        elif any(item in normalized for item in ("research", "調べ", "比較")) and not any(
            item in normalized for item in ("実装", "作って", "build", "implement", "实现")
        ):
            mode = "research"
        else:
            mode = "build"
    return {"triggered": triggered, "mode": mode}


def normalize_message(text: str) -> str:
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+", "[REDACTED]", text)
    text = re.sub(r"gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}", "[REDACTED]", text)
    text = re.sub(r"0x[0-9a-fA-F]+", "<hex>", text.casefold())
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<num>", text)
    return re.sub(r"\s+", " ", text).strip()[:1000]


def fingerprint(data: dict[str, Any]) -> str:
    canonical = {
        "command_category": data.get("command_category", "unknown"),
        "error_category": data.get("error_category", "unknown"),
        "target": data.get("target", "unknown"),
        "message": normalize_message(str(data.get("message", ""))),
        "root_cause": normalize_message(str(data.get("suspected_root_cause", ""))),
        "environment": data.get("environment", {}),
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def score(data: dict[str, Any]) -> dict[str, Any]:
    risks = set(map(str, data.get("risks", [])))
    disqualified = sorted(risks & DISQUALIFIERS)
    total = 0.0
    for key, weight in WEIGHTS.items():
        value = float(data.get("scores", {}).get(key, 0))
        if not 0 <= value <= 1:
            raise ValueError(f"{key} must be between 0 and 1")
        total += value * weight
    return {"id": data.get("id"), "total": round(total, 2), "eligible": not disqualified, "disqualified_by": disqualified}


def budget(data: dict[str, Any]) -> dict[str, Any]:
    limits = data.get("limits", {})
    used = data.get("used", {})
    exceeded = {key: {"used": used.get(key, 0), "limit": value} for key, value in limits.items() if used.get(key, 0) > value}
    return {"valid": not exceeded, "exceeded": exceeded, "remaining": {key: max(0, value - used.get(key, 0)) for key, value in limits.items()}}


def progress(data: dict[str, Any]) -> dict[str, Any]:
    previous = data.get("previous", {})
    current = data.get("current", {})
    improved = (
        current.get("acceptance_passed", 0) > previous.get("acceptance_passed", 0)
        or current.get("tests_passed", 0) > previous.get("tests_passed", 0)
        or current.get("incomplete_tasks", 0) < previous.get("incomplete_tasks", 0)
        or current.get("blockers", 0) < previous.get("blockers", 0)
        or current.get("uncertainty", 0) < previous.get("uncertainty", 0)
        or current.get("root_causes", 0) > previous.get("root_causes", 0)
        or current.get("safe_alternatives", 0) > previous.get("safe_alternatives", 0)
    )
    return {"improved": improved}


def checkpoint(data: dict[str, Any], output: Path) -> dict[str, Any]:
    required = ("run_id", "project_identity", "status", "current_phase", "next_action")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"Missing checkpoint fields: {missing}")
    payload = {"schema_version": "1.0", "timestamp": datetime.now(UTC).isoformat(), **data}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["integrity_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"checkpoint": str(output)}


def read_object(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("invocation")
    inv.add_argument("text")
    for name in ("score", "fingerprint", "budget", "progress"):
        item = sub.add_parser(name)
        item.add_argument("file")
    cp = sub.add_parser("checkpoint")
    cp.add_argument("file")
    cp.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "invocation":
            result = invocation(args.text)
        elif args.command == "score":
            result = score(read_object(args.file))
        elif args.command == "fingerprint":
            result = {"fingerprint": fingerprint(read_object(args.file))}
        elif args.command == "budget":
            result = budget(read_object(args.file))
        elif args.command == "progress":
            result = progress(read_object(args.file))
        else:
            result = checkpoint(read_object(args.file), Path(args.output))
        emit(result)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
