from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib

DEFAULT_LIMITS: dict[str, int] = {
    "research_rounds": 3,
    "broad_candidates": 12,
    "deep_review_candidates": 3,
    "repository_clones": 1,
    "acquisition_attempts_per_capability": 2,
    "research_reentries": 1,
    "architecture_replans": 2,
    "attempts_per_task": 3,
    "same_failure_repetitions": 2,
    "stagnation_cycles": 2,
    "scope_additions": 5,
    "tool_calls": 120,
    "changed_files_soft_limit": 80,
}

PROFILE_OVERRIDES: dict[str, dict[str, int]] = {
    "quick": {
        "research_rounds": 1,
        "deep_review_candidates": 1,
        "architecture_replans": 1,
        "attempts_per_task": 2,
        "tool_calls": 50,
    },
    "standard": {},
    "deep": {
        "research_rounds": 5,
        "broad_candidates": 20,
        "deep_review_candidates": 5,
        "repository_clones": 2,
        "architecture_replans": 3,
        "attempts_per_task": 4,
        "tool_calls": 220,
    },
}


@dataclass(frozen=True, slots=True)
class Config:
    schema_version: str
    mode: str
    budget_profile: str
    autonomy: str
    language: str
    limits: dict[str, int]
    approval: dict[str, bool]
    state: dict[str, bool]


def default_config(profile: str = "standard") -> Config:
    if profile not in PROFILE_OVERRIDES:
        raise ValueError(f"Unknown budget profile: {profile}")
    limits = DEFAULT_LIMITS | PROFILE_OVERRIDES[profile]
    return Config(
        schema_version="1.0",
        mode="build",
        budget_profile=profile,
        autonomy="guarded",
        language="auto",
        limits=limits,
        approval={
            "global_write": True,
            "secret_access": True,
            "billable_action": True,
            "publication": True,
            "privileged": True,
            "external_binary": True,
            "network_write": True,
        },
        state={
            "commit_project_decisions": True,
            "ignore_runtime_runs": True,
            "checkpoint_on_stop": True,
            "checkpoint_on_complete": False,
        },
    )


def load_config(path: Path) -> Config:
    if not path.exists():
        return default_config()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Project config must be a regular non-symlink file: {path}")
    with path.open("rb") as handle:
        raw: dict[str, Any] = tomllib.load(handle)

    schema_version = str(raw.get("schema_version", "1.0"))
    if schema_version != "1.0":
        raise ValueError(f"Unsupported config schema_version: {schema_version}")

    profile = str(raw.get("budget_profile", "standard"))
    if profile == "deep":
        raise ValueError("Project config may not select the deep budget profile; pass --budget deep explicitly")
    base = default_config(profile)

    raw_limits = raw.get("limits", {})
    if not isinstance(raw_limits, dict):
        raise ValueError("Config [limits] must be a table")
    limits = dict(base.limits)
    for raw_key, raw_value in raw_limits.items():
        key = str(raw_key)
        if key not in base.limits:
            raise ValueError(f"Unknown budget limit in project config: {key}")
        value = int(raw_value)
        if value <= 0:
            raise ValueError(f"Budget limit must be positive: {key}={value}")
        if value > base.limits[key]:
            raise ValueError(
                f"Project config may only tighten budget limits: {key}={value} exceeds {base.limits[key]}"
            )
        limits[key] = value

    raw_approval = raw.get("approval", {})
    if not isinstance(raw_approval, dict):
        raise ValueError("Config [approval] must be a table")
    approval = dict(base.approval)
    for raw_key, raw_value in raw_approval.items():
        key = str(raw_key)
        if key not in base.approval:
            raise ValueError(f"Unknown approval policy in project config: {key}")
        value = bool(raw_value)
        if base.approval[key] and not value:
            raise ValueError(f"Project config may not disable required approval: {key}")
        approval[key] = value

    autonomy = str(raw.get("autonomy", "guarded"))
    if autonomy != "guarded":
        raise ValueError("Project config may not weaken autonomy below guarded")

    raw_state = raw.get("state", {})
    if not isinstance(raw_state, dict):
        raise ValueError("Config [state] must be a table")
    state = base.state | {str(k): bool(v) for k, v in raw_state.items()}
    return Config(
        schema_version=schema_version,
        mode=str(raw.get("mode", "build")),
        budget_profile=profile,
        autonomy=autonomy,
        language=str(raw.get("language", "auto")),
        limits=limits,
        approval=approval,
        state=state,
    )
