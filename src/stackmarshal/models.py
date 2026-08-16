from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .constants import Mode, Phase, SCHEMA_VERSION, Status


@dataclass(slots=True)
class ProjectInfo:
    root: str
    git_head: str | None = None
    identity_hash: str | None = None
    dirty: bool = False
    git_toplevel: str | None = None
    repository_owned: bool = False
    repository_lineage: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Invocation:
    explicit: bool
    raw_text: str
    language: str = "auto"


@dataclass(slots=True)
class BudgetState:
    profile: str
    limits: dict[str, int]
    used: dict[str, int] = field(default_factory=dict)

    def remaining(self) -> dict[str, int]:
        return {key: max(0, value - self.used.get(key, 0)) for key, value in self.limits.items()}


@dataclass(slots=True)
class ProgressSnapshot:
    acceptance_passed: int = 0
    tests_passed: int = 0
    incomplete_tasks: int = 0
    blockers: int = 0
    uncertainty: int = 0
    root_causes: int = 0
    safe_alternatives: int = 0

    def score(self) -> int:
        return (
            self.acceptance_passed * 5
            + self.tests_passed * 2
            - self.incomplete_tasks * 3
            - self.blockers * 5
            - self.uncertainty * 2
            + self.root_causes * 2
            + self.safe_alternatives
        )


@dataclass(slots=True)
class RunState:
    run_id: str
    project: ProjectInfo
    invocation: Invocation
    mode: Mode
    budget: BudgetState
    phase: Phase = Phase.INVOCATION_CHECK
    status: Status = Status.RUNNING
    progress: dict[str, Any] = field(default_factory=dict)
    stop_reason: dict[str, Any] | None = None
    completed_phases: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        data["phase"] = self.phase.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        return cls(
            schema_version=str(data["schema_version"]),
            run_id=str(data["run_id"]),
            project=ProjectInfo(**data["project"]),
            invocation=Invocation(**data["invocation"]),
            mode=Mode(data["mode"]),
            phase=Phase(data["phase"]),
            status=Status(data["status"]),
            budget=BudgetState(**data["budget"]),
            progress=dict(data.get("progress", {})),
            stop_reason=data.get("stop_reason"),
            completed_phases=list(data.get("completed_phases", [])),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )

    @property
    def root(self) -> Path:
        return Path(self.project.root)
