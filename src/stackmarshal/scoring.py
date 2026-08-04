from __future__ import annotations

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
    "no_license",
    "archived",
    "incompatible_platform",
    "critical_known_vulnerability",
    "unapproved_secret_requirement",
    "suspicious_install_hook",
    "unreviewable_binary",
    "cannot_pin_version",
    "excessive_permissions",
}


def score_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    risks = {str(item) for item in candidate.get("risks", [])}
    disqualified_by = sorted(risks & DISQUALIFIERS)
    raw = candidate.get("scores", {})
    normalized: dict[str, float] = {}
    total = 0.0
    for key, weight in WEIGHTS.items():
        value = float(raw.get(key, 0))
        if not 0 <= value <= 1:
            raise ValueError(f"{key} must be between 0 and 1")
        normalized[key] = value
        total += value * weight
    return {
        "id": candidate.get("id"),
        "total": round(total, 2),
        "components": normalized,
        "disqualified": bool(disqualified_by),
        "disqualified_by": disqualified_by,
        "eligible": not disqualified_by,
    }
