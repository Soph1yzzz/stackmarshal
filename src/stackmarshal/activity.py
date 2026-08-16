from __future__ import annotations

from typing import Any

from .budget import consume
from .constants import Phase
from .models import RunState

_COUNTER_BY_KIND = {
    "tool-call": "tool_calls",
    "research-round": "research_rounds",
    "architecture-replan": "architecture_replans",
    "failure-repeat": "same_failure_repetitions",
    "stagnation-cycle": "stagnation_cycles",
    "scope-addition": "scope_additions",
}

class ActivityBudgetExhausted(ValueError):
    def __init__(self, counter: str, attempted: int, limit: int) -> None:
        self.counter = counter
        self.attempted = attempted
        self.limit = limit
        super().__init__(f"Budget exhausted for {counter}: {attempted}>{limit}")


_ALLOWED_PHASES = {
    "implementation": {Phase.IMPLEMENTATION},
    "verification": {Phase.VERIFICATION},
    "task-attempt": {Phase.IMPLEMENTATION, Phase.VERIFICATION},
    "research-round": {Phase.RESEARCH_GATE, Phase.LANDSCAPE_RESEARCH},
    "architecture-replan": {Phase.REPLAN, Phase.ARCHITECTURE_FREEZE},
    "failure-repeat": {Phase.IMPLEMENTATION, Phase.VERIFICATION, Phase.REPLAN},
    "stagnation-cycle": {Phase.IMPLEMENTATION, Phase.VERIFICATION, Phase.REPLAN},
    "scope-addition": {Phase.IMPLEMENTATION, Phase.REPLAN},
}


def record_activity(
    state: RunState,
    kind: str,
    *,
    amount: int = 1,
    task_id: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("Activity amount must be positive")
    allowed = _ALLOWED_PHASES.get(kind)
    if allowed is not None and state.phase not in allowed:
        raise ValueError(f"Activity {kind!r} is not allowed during {state.phase.value}")

    budget_counter: str | None
    if kind == "task-attempt":
        if not task_id:
            raise ValueError("task-attempt requires task_id")
        attempts = state.progress.setdefault("task_attempts", {})
        if not isinstance(attempts, dict):
            raise ValueError("Invalid task_attempts progress state")
        proposed = int(attempts.get(task_id, 0)) + amount
        limit = state.budget.limits.get("attempts_per_task")
        if limit is None:
            raise ValueError("Budget has no attempts_per_task counter")
        if proposed > limit:
            raise ActivityBudgetExhausted("attempts_per_task", proposed, limit)
        attempts[task_id] = proposed
        state.budget.used["attempts_per_task"] = max(
            proposed, state.budget.used.get("attempts_per_task", 0)
        )
        budget_counter = "attempts_per_task"
        used = proposed
        limit_value = limit
    else:
        budget_counter = _COUNTER_BY_KIND.get(kind)
        if budget_counter:
            decision = consume(state.budget, budget_counter, amount)
            if not decision.allowed:
                attempted = state.budget.used.get(budget_counter, 0) + amount
                raise ActivityBudgetExhausted(budget_counter, attempted, decision.limit)
            used = decision.used
            limit_value = decision.limit
        else:
            used = None
            limit_value = None

    counts = state.progress.setdefault("activity_counts", {})
    if not isinstance(counts, dict):
        raise ValueError("Invalid activity_counts progress state")
    counts[kind] = int(counts.get(kind, 0)) + amount
    by_phase = state.progress.setdefault("activity_by_phase", {})
    if not isinstance(by_phase, dict):
        raise ValueError("Invalid activity_by_phase progress state")
    phase_counts = by_phase.setdefault(state.phase.value, {})
    if not isinstance(phase_counts, dict):
        raise ValueError("Invalid phase activity progress state")
    phase_counts[kind] = int(phase_counts.get(kind, 0)) + amount
    record = {
        "kind": kind,
        "amount": amount,
        "task_id": task_id,
        "detail": detail,
        "phase": state.phase.value,
        "budget_counter": budget_counter,
        "budget_used": used,
        "budget_limit": limit_value,
    }
    return record


def completion_activity_errors(state: RunState) -> list[str]:
    if state.mode.value != "build":
        return []
    counts = state.progress.get("activity_counts", {})
    if not isinstance(counts, dict):
        return ["invalid_activity_counts"]
    errors: list[str] = []
    if int(counts.get("implementation", 0)) <= 0:
        errors.append("missing_live_implementation_activity")
    if int(counts.get("verification", 0)) <= 0:
        errors.append("missing_live_verification_activity")
    if state.budget.used.get("tool_calls", 0) <= 0:
        errors.append("untouched_tool_call_budget")
    by_phase = state.progress.get("activity_by_phase", {})
    if not isinstance(by_phase, dict):
        errors.append("invalid_activity_by_phase")
    else:
        implementation = by_phase.get(Phase.IMPLEMENTATION.value, {})
        verification = by_phase.get(Phase.VERIFICATION.value, {})
        implementation_tools = (
            int(implementation.get("tool-call", 0)) if isinstance(implementation, dict) else 0
        )
        verification_tools = (
            int(verification.get("tool-call", 0)) if isinstance(verification, dict) else 0
        )
        if implementation_tools <= 0:
            errors.append("missing_implementation_tool_activity")
        if verification_tools <= 0:
            errors.append("missing_verification_tool_activity")
    return errors
