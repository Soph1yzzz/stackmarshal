from __future__ import annotations

from dataclasses import asdict

from .models import ProgressSnapshot


def evaluate(previous: ProgressSnapshot | None, current: ProgressSnapshot) -> dict[str, object]:
    if previous is None:
        return {"improved": True, "delta": current.score(), "current": asdict(current)}
    delta = current.score() - previous.score()
    improved_fields = []
    if current.acceptance_passed > previous.acceptance_passed:
        improved_fields.append("acceptance_passed")
    if current.tests_passed > previous.tests_passed:
        improved_fields.append("tests_passed")
    if current.incomplete_tasks < previous.incomplete_tasks:
        improved_fields.append("incomplete_tasks")
    if current.blockers < previous.blockers:
        improved_fields.append("blockers")
    if current.uncertainty < previous.uncertainty:
        improved_fields.append("uncertainty")
    if current.root_causes > previous.root_causes:
        improved_fields.append("root_causes")
    if current.safe_alternatives > previous.safe_alternatives:
        improved_fields.append("safe_alternatives")
    return {
        "improved": bool(improved_fields),
        "delta": delta,
        "improved_fields": improved_fields,
        "previous": asdict(previous),
        "current": asdict(current),
    }
