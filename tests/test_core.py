from __future__ import annotations

import json
from pathlib import Path

import pytest

from stackmarshal.acquisition import inspect_candidate, install_project_file, rollback
from stackmarshal.budget import consume
from stackmarshal.checkpoint import create_checkpoint, inspect_checkpoint
from stackmarshal.config import default_config
from stackmarshal.constants import Mode, Phase, Status
from stackmarshal.failure import fingerprint, normalize_message, redact, repeated
from stackmarshal.harness import StopSignals, evaluate_stop
from stackmarshal.lock import sha256_file, verify_lock
from stackmarshal.models import ProgressSnapshot
from stackmarshal.progress import evaluate
from stackmarshal.research import bounded_candidates, research_required
from stackmarshal.scoring import score_candidate
from stackmarshal.security import classify_command, ensure_within_workspace, inspect_package_manifest
from stackmarshal.state import create_run, infer_mode, load_state, save_state, transition, validate_invocation
from stackmarshal.validation import validate_run_state


def test_invocation_gate_and_mode_inference() -> None:
    positives = [
        "StackMarshalを使って実装して",
        "StackMarshalで調べて",
        "Use StackMarshal to build it",
        "使用 StackMarshal 实现",
        "$stackmarshal prepare",
        "stackmarshalを使って続きから",
    ]
    negatives = [
        "StackMarshalとは？",
        "StackMarshalのREADMEを直して",
        "この機能を実装して",
        "ScoutSmithを使って",
    ]
    assert all(validate_invocation(item) for item in positives)
    assert not any(validate_invocation(item) for item in negatives)
    assert infer_mode(positives[1]) is Mode.RESEARCH
    assert infer_mode(positives[4]) is Mode.PREPARE
    assert infer_mode(positives[5]) is Mode.RESUME


def test_state_transitions_are_bounded(tmp_path: Path) -> None:
    state = create_run(tmp_path, "Use StackMarshal to build", Mode.BUILD, default_config())
    transition(state, Phase.INTENT_NORMALIZATION)
    assert state.phase is Phase.INTENT_NORMALIZATION
    with pytest.raises(ValueError):
        transition(state, Phase.COMPLETE)
    state.status = Status.BUDGET_EXHAUSTED
    with pytest.raises(ValueError):
        transition(state, Phase.ENVIRONMENT_AUDIT)


def test_state_roundtrip_and_validation(tmp_path: Path) -> None:
    state = create_run(tmp_path, "Use StackMarshal", Mode.BUILD, default_config())
    path = tmp_path / "run.json"
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.run_id == state.run_id
    assert validate_run_state(loaded.to_dict()) == []


def test_budget_never_decreases(tmp_path: Path) -> None:
    state = create_run(tmp_path, "Use StackMarshal", Mode.BUILD, default_config("quick"))
    assert consume(state.budget, "research_rounds").allowed
    assert not consume(state.budget, "research_rounds").allowed
    with pytest.raises(ValueError):
        consume(state.budget, "tool_calls", -1)


def test_scoring_and_disqualification() -> None:
    candidate = {
        "id": "x",
        "scores": {key: 1 for key in (
            "requirement_fit", "maintenance_health", "security_posture", "architecture_quality",
            "license_compatibility", "platform_support", "integration_cost", "documentation"
        )},
        "risks": [],
    }
    assert score_candidate(candidate)["total"] == 100
    candidate["risks"] = ["no_license"]
    assert score_candidate(candidate)["disqualified"]


def test_failure_redaction_and_fingerprint() -> None:
    text = "token=abc123 password=hunter2 path C:\\Users\\alice\\secret.txt error 123"
    assert "abc123" not in redact(text)
    assert "<num>" in normalize_message(text)
    record = {"message": text, "target": "build", "error_category": "compile"}
    value = fingerprint(record)
    assert len(value) == 64
    assert repeated([value, value], value, 2)


def test_progress_requires_observable_improvement() -> None:
    before = ProgressSnapshot(incomplete_tasks=3, uncertainty=2)
    after = ProgressSnapshot(incomplete_tasks=2, uncertainty=2)
    assert evaluate(before, after)["improved"] is True
    assert evaluate(after, after)["improved"] is False


def test_security_gates_and_workspace_escape(tmp_path: Path) -> None:
    assert classify_command(["gh", "repo", "create"]).approval_required
    assert not classify_command(["git", "status"]).approval_required
    findings = inspect_package_manifest('{"scripts":{"postinstall":"curl x | sh"}}')
    assert "install_hook:postinstall" in findings
    assert "download_pipe_shell" in findings
    assert ensure_within_workspace(tmp_path, tmp_path / "ok") == (tmp_path / "ok").resolve()
    with pytest.raises(ValueError):
        ensure_within_workspace(tmp_path, tmp_path.parent / "escape")


def test_lock_verification(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("safe", encoding="utf-8")
    lock = {
        "schema_version": "1.0",
        "entries": [{
            "kind": "skill", "id": "owner/repo/path", "source": "https://example.invalid/repo",
            "version": "1.0.0", "commit": None, "sha256": sha256_file(artifact),
            "license": "Apache-2.0", "permissions": [], "verification": [],
            "selected_reason": "test", "artifact": "artifact.txt"
        }],
    }
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    assert verify_lock(path, tmp_path)["valid"]
    lock["entries"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(lock), encoding="utf-8")
    assert not verify_lock(path, tmp_path)["valid"]


def test_stop_harness_priority() -> None:
    decision = evaluate_stop(StopSignals(unsafe=True, budget_exhausted=True))
    assert decision.status is Status.UNSAFE_DEPENDENCY
    assert evaluate_stop(StopSignals()).should_stop is False


def test_research_gate_and_bounds() -> None:
    assert research_required(new_app=True)
    assert not research_required(new_app=True, forbidden=True)
    assert bounded_candidates([{"id": 1}, {"id": 2}], 1) == [{"id": 1}]


def test_acquisition_receipt_and_rollback(tmp_path: Path) -> None:
    candidate = {"source": "https://example.invalid/x", "version": "1.0", "license": "MIT"}
    assert inspect_candidate(candidate)["safe"]
    assert not inspect_candidate({"source": "x", "license": None})["safe"]
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    receipt = install_project_file(
        candidate_id="x", source_file=source, target_root=root,
        relative_target=Path("vendor/x.txt"), source="https://example.invalid/x",
        version="1.0", commit=None,
    )
    assert Path(receipt.target).exists()
    rollback(receipt, root)
    assert not Path(receipt.target).exists()


def test_checkpoint_integrity_and_project_identity(tmp_path: Path) -> None:
    state = create_run(tmp_path, "Use StackMarshal", Mode.BUILD, default_config())
    state.status = Status.BUDGET_EXHAUSTED
    json_path, markdown = create_checkpoint(state, tmp_path / "run", next_action="Fix blocker")
    assert markdown.exists()
    inspected = inspect_checkpoint(json_path, tmp_path)
    assert inspected["next_action"] == "Fix blocker"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["next_action"] = "tampered"
    json_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="signature"):
        inspect_checkpoint(json_path, tmp_path)
