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
    with path.open("rb") as handle:
        raw: dict[str, Any] = tomllib.load(handle)
    profile = str(raw.get("budget_profile", "standard"))
    base = default_config(profile)
    limits = base.limits | {str(k): int(v) for k, v in raw.get("limits", {}).items()}
    approval = base.approval | {str(k): bool(v) for k, v in raw.get("approval", {}).items()}
    state = base.state | {str(k): bool(v) for k, v in raw.get("state", {}).items()}
    return Config(
        schema_version=str(raw.get("schema_version", "1.0")),
        mode=str(raw.get("mode", "build")),
        budget_profile=profile,
        autonomy=str(raw.get("autonomy", "guarded")),
        language=str(raw.get("language", "auto")),
        limits=limits,
        approval=approval,
        state=state,
    )
