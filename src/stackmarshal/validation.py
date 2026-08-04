from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import Mode, Phase, SCHEMA_VERSION, Status


def validate_run_state(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"schema_version", "run_id", "project", "invocation", "mode", "phase", "status", "budget", "progress"}
    for key in sorted(required - set(data)):
        errors.append(f"missing:{key}")
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported_schema_version")
    try:
        Mode(str(data.get("mode")))
    except ValueError:
        errors.append("invalid_mode")
    try:
        Phase(str(data.get("phase")))
    except ValueError:
        errors.append("invalid_phase")
    try:
        Status(str(data.get("status")))
    except ValueError:
        errors.append("invalid_status")
    invocation = data.get("invocation", {})
    if not isinstance(invocation, dict) or invocation.get("explicit") is not True:
        errors.append("invocation_not_explicit")
    budget = data.get("budget", {})
    if not isinstance(budget, dict):
        errors.append("invalid_budget")
        return errors
    limits = budget.get("limits", {})
    used = budget.get("used", {})
    if not isinstance(limits, dict) or not isinstance(used, dict):
        errors.append("invalid_budget_counters")
        return errors
    for key, value in used.items():
        try:
            used_value = int(value)
            limit_value = int(limits[key]) if key in limits else None
        except (TypeError, ValueError):
            errors.append(f"invalid_budget_value:{key}")
            continue
        if used_value < 0:
            errors.append(f"negative_budget:{key}")
        if limit_value is not None and used_value > limit_value:
            errors.append(f"budget_exceeded:{key}")
    return errors


def validate_json_file(path: Path, kind: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    if not isinstance(data, dict):
        return {"valid": False, "errors": ["expected_json_object"]}
    if kind == "run-state":
        errors = validate_run_state(data)
    elif kind == "candidate":
        required = {"id", "kind", "source", "scores", "risks", "decision"}
        errors = [f"missing:{key}" for key in sorted(required - set(data))]
    elif kind == "capability-map":
        errors = [] if data.get("schema_version") == "1.0" and isinstance(data.get("capabilities"), list) else ["invalid_capability_map"]
    elif kind == "checkpoint":
        required = {"schema_version", "run_id", "project_identity", "status", "current_phase", "next_action"}
        errors = [f"missing:{key}" for key in sorted(required - set(data))]
    else:
        errors = [f"unknown_kind:{kind}"]
    return {"valid": not errors, "errors": errors}
