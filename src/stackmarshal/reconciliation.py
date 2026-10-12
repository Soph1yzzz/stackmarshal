"""Read-only comparison between authenticated run evidence and live workspace facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import Status
from .integrity import ensure_signing_key_outside, verify_record
from .state import project_info, terminal_workspace_fingerprint, worktree_fingerprint
from .taskgraph import load_task_graph
from .models import RunState


def reconcile_evidence(root: Path, state: RunState) -> dict[str, Any]:
    """Observe divergences, never modify the project or promote outside work."""

    root = root.resolve(strict=True)
    if root != Path(state.project.root).resolve():
        raise ValueError("Evidence run belongs to another workspace")
    current = project_info(root)
    reasons: list[str] = []
    saved_head = state.project.git_head
    if saved_head != current.git_head:
        reasons.append("git_head_changed")
    if state.project.identity_hash != current.identity_hash:
        reasons.append("project_identity_changed")
    checkpoint_path = root / ".stackmarshal" / "runs" / state.run_id / "checkpoint.json"
    checkpoint: dict[str, Any] | None = None
    if checkpoint_path.exists():
        if checkpoint_path.is_symlink():
            raise ValueError("Checkpoint is a symlink")
        ensure_signing_key_outside(root)
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Checkpoint must be an object")
        verify_record(payload)
        if payload.get("run_id") != state.run_id:
            raise ValueError("Checkpoint belongs to another run")
        checkpoint = payload
        if checkpoint.get("git_head") != current.git_head:
            reasons.append("checkpoint_git_head_changed")
        if checkpoint.get("project_identity") != current.identity_hash:
            reasons.append("checkpoint_identity_changed")
        if checkpoint.get("dirty") != current.dirty:
            reasons.append("checkpoint_dirty_state_changed")
        try:
            if checkpoint.get("worktree_fingerprint") != worktree_fingerprint(root):
                reasons.append("checkpoint_worktree_changed")
        except ValueError as exc:
            reasons.append(f"fingerprint_diagnostic:{exc}")
    verified = state.progress.get("verified_workspace")
    if isinstance(verified, dict):
        try:
            if verified.get("workspace_fingerprint") != terminal_workspace_fingerprint(root):
                reasons.append("verified_workspace_changed")
        except ValueError as exc:
            reasons.append(f"verification_diagnostic:{exc}")
    graph = load_task_graph(root)
    incomplete = [
        str(task.get("id")) for task in graph["tasks"]
        if task.get("mandatory", True) and task.get("status") != "done"
    ]
    verified_matches = isinstance(verified, dict) and "verified_workspace_changed" not in reasons
    if not verified_matches and "verification_diagnostic:" not in " ".join(reasons):
        reasons.append("no_current_verified_workspace")
    return {
        "policy": "read_only_no_trust_promotion",
        "run_id": state.run_id,
        "run_status": state.status.value,
        "git": {"recorded_head": saved_head, "current_head": current.git_head,
                "recorded_dirty": state.project.dirty, "current_dirty": current.dirty},
        "checkpoint_present": checkpoint is not None,
        "mandatory_tasks_incomplete": incomplete,
        "evidence_state": "stale" if reasons else "matching",
        "differences": reasons,
        "external_work": "unverified" if reasons else "not_inferred",
        "completion_claimable": state.status is Status.COMPLETE and not reasons and not incomplete,
    }
