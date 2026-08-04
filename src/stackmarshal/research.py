from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvidenceBundle:
    selected_patterns: list[str] = field(default_factory=list)
    rejected_patterns: list[str] = field(default_factory=list)
    pitfalls: list[str] = field(default_factory=list)
    selected_dependencies: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_patterns": self.selected_patterns,
            "rejected_patterns": self.rejected_patterns,
            "pitfalls": self.pitfalls,
            "selected_dependencies": self.selected_dependencies,
            "constraints": self.constraints,
            "open_questions": self.open_questions,
            "sources": self.sources,
        }


def bounded_candidates(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit < 0:
        raise ValueError("Candidate limit cannot be negative")
    return candidates[:limit]


def research_required(*, new_app: bool = False, architecture_choice: bool = False,
                      external_integration: bool = False, security_sensitive: bool = False,
                      unknown_technology: bool = False, new_dependency: bool = False,
                      large_refactor: bool = False, fixed_technology: bool = False,
                      trivial_edit: bool = False, forbidden: bool = False) -> bool:
    if forbidden or trivial_edit or fixed_technology:
        return False
    return any((new_app, architecture_choice, external_integration, security_sensitive,
                unknown_technology, new_dependency, large_refactor))
