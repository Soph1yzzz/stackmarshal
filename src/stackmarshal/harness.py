from __future__ import annotations

from dataclasses import dataclass

from .constants import Status


@dataclass(frozen=True, slots=True)
class StopSignals:
    unsafe: bool = False
    user_cancelled: bool = False
    approval_required: bool = False
    invalid_state: bool = False
    budget_exhausted: bool = False
    repeated_failure: bool = False
    stagnated: bool = False
    scope_drift: bool = False
    external_blocker: bool = False
    verification_external_blocked: bool = False


@dataclass(frozen=True, slots=True)
class StopDecision:
    should_stop: bool
    status: Status | None
    reason: str | None


_STOP_ORDER: tuple[tuple[str, Status, str], ...] = (
    ("unsafe", Status.UNSAFE_DEPENDENCY, "Safety cannot be established"),
    ("user_cancelled", Status.USER_CANCELLED, "The user cancelled the run"),
    ("approval_required", Status.APPROVAL_REQUIRED, "Explicit approval is required"),
    ("invalid_state", Status.INVALID_STATE, "The run state is invalid"),
    ("budget_exhausted", Status.BUDGET_EXHAUSTED, "A hard budget was exhausted"),
    ("repeated_failure", Status.REPEATED_FAILURE, "A failure fingerprint reached its limit"),
    ("stagnated", Status.STAGNATED, "No observable progress remained after replanning"),
    ("scope_drift", Status.SCOPE_DRIFT, "The required scope exceeded its bounded allowance"),
    ("verification_external_blocked", Status.VERIFICATION_EXTERNAL_BLOCKED, "External verification is temporarily blocked"),
    ("external_blocker", Status.BLOCKED_EXTERNAL, "An external dependency blocks progress"),
)


def evaluate_stop(signals: StopSignals) -> StopDecision:
    for attribute, status, reason in _STOP_ORDER:
        if getattr(signals, attribute):
            return StopDecision(True, status, reason)
    return StopDecision(False, None, None)
