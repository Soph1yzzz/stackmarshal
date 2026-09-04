from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import stackmarshal.cli as cli_module
from stackmarshal.activity import record_activity
from stackmarshal.checkpoint import create_checkpoint
from stackmarshal.cli import EXIT_INVALID_INPUT, main
from stackmarshal.config import default_config
from stackmarshal.constants import Mode, Phase, Status, __version__
from stackmarshal.harness import StopSignals, evaluate_stop
from stackmarshal.state import create_run, load_state, save_state, transition
from stackmarshal.taskgraph import save_task_graph


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, object]]:
    code = main(argv)
    captured = capsys.readouterr()
    text = captured.out.strip() or captured.err.strip()
    return code, json.loads(text)


def _state_at(root: Path, phase: Phase = Phase.VERIFICATION) -> tuple[Path, object]:
    state = create_run(root, "Use StackMarshal to implement this", Mode.BUILD, default_config())
    state.phase = phase
    path = root / ".stackmarshal" / "runs" / state.run_id / "run.json"
    save_state(state, path)
    return path, state


def test_checkpoint_ready_resumes_same_run_after_integrity_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    path, state = _state_at(root)

    code, checkpoint = _call(
        capsys,
        ["--root", str(root), "checkpoint", "create", "--run-id", state.run_id, "--next-action", "continue verification"],
    )
    assert code == 0
    assert checkpoint["succeeded"] is True
    assert checkpoint["status"] == Status.CHECKPOINT_READY.value
    checkpoint_data = json.loads(Path(str(checkpoint["checkpoint"])).read_text(encoding="utf-8"))
    assert checkpoint_data["resume_phase"] == Phase.VERIFICATION.value
    assert checkpoint_data["resume_command"] == f"stackmarshal resume {state.run_id}"

    code, resumed = _call(
        capsys,
        ["--root", str(root), "resume", state.run_id, "--reason", "owner approved substitute reviewer"],
    )
    assert code == 0
    assert resumed["resumed"] is True
    assert resumed["run_id"] == state.run_id
    assert resumed["phase"] == Phase.VERIFICATION.value
    restored = load_state(path, project_root=root)
    assert restored.status is Status.RUNNING
    assert restored.phase is Phase.VERIFICATION
    assert restored.stop_reason is None
    assert restored.progress["resolved_stops"][-1]["resolution"] == "owner approved substitute reviewer"


def test_resume_rejects_workspace_change_after_checkpoint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _, state = _state_at(root)
    code, _ = _call(
        capsys,
        ["--root", str(root), "checkpoint", "create", "--run-id", state.run_id, "--next-action", "continue"],
    )
    assert code == 0
    (root / "changed-after-checkpoint.txt").write_text("changed", encoding="utf-8")

    code, error = _call(capsys, ["--root", str(root), "resume", state.run_id])
    assert code == EXIT_INVALID_INPUT
    assert "fingerprint mismatch" in str(error["error"]).lower()


def test_legacy_unsigned_state_is_archived_without_trust_promotion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    code, _ = _call(capsys, ["--root", str(root), "init"])
    assert code == 0
    run_id = "20260101-000000-deadbeef"
    legacy_dir = root / ".stackmarshal" / "runs" / run_id
    legacy_dir.mkdir(parents=True)
    legacy_bytes = b'{"schema_version":"1.0","run_id":"20260101-000000-deadbeef","status":"RUNNING"}\n'
    (legacy_dir / "run.json").write_bytes(legacy_bytes)
    (legacy_dir / "notes.txt").write_text("historical evidence", encoding="utf-8")

    code, error = _call(
        capsys,
        ["--root", str(root), "start", "--invocation", "Use StackMarshal to implement this"],
    )
    assert code == EXIT_INVALID_INPUT
    assert "stackmarshal migrate" in str(error["error"])

    code, migrated = _call(capsys, ["--root", str(root), "migrate"])
    assert code == 0
    assert migrated["migrated"] is True
    assert not legacy_dir.exists()
    archive = root / str(migrated["archive"])
    archived_run = archive / "runs" / run_id / "run.json"
    assert archived_run.read_bytes() == legacy_bytes
    manifest = json.loads((archive / "archive-manifest.json").read_text(encoding="utf-8"))
    assert manifest["reason"] == "legacy_unsigned_state_archived_without_trust_promotion"
    assert any(item["path"] == f"runs/{run_id}/run.json" for item in manifest["files"])

    code, started = _call(
        capsys,
        ["--root", str(root), "start", "--invocation", "Use StackMarshal to implement this"],
    )
    assert code == 0
    assert started["started"] is True
    assert started["run_id"] != run_id


def test_migration_refuses_partial_integrity_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    run_id = "20260101-000000-cafebabe"
    legacy_dir = root / ".stackmarshal" / "runs" / run_id
    legacy_dir.mkdir(parents=True)
    state_path = legacy_dir / "run.json"
    state_path.write_text(
        json.dumps({"schema_version": "1.0", "run_id": run_id, "integrity_algorithm": "hmac-sha256-v1"}),
        encoding="utf-8",
    )

    code, error = _call(capsys, ["--root", str(root), "migrate"])
    assert code == EXIT_INVALID_INPUT
    assert "partial or unsupported integrity envelope" in str(error["error"])
    assert state_path.exists()


def test_verification_correction_lane_does_not_consume_replan_budget(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    state = create_run(root, "Use StackMarshal to implement this", Mode.BUILD, default_config())
    state.phase = Phase.VERIFICATION

    transition(state, Phase.CORRECTION)
    record = record_activity(state, "correction", detail="fix exactOptionalPropertyTypes fixture")
    transition(state, Phase.VERIFICATION)

    assert record["phase"] == Phase.CORRECTION.value
    assert state.phase is Phase.VERIFICATION
    assert state.budget.used.get("architecture_replans", 0) == 0


def test_mandatory_external_task_block_propagates_into_checkpoint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    path, state = _state_at(root)
    save_task_graph(
        root,
        {
            "schema_version": "1.0",
            "tasks": [
                {
                    "id": "T5",
                    "summary": "Fresh review",
                    "mandatory": True,
                    "acceptance": ["review completed"],
                    "status": "pending",
                    "attempts": 0,
                    "evidence": [],
                }
            ],
        },
    )

    code, blocked = _call(
        capsys,
        ["--root", str(root), "task", "block", "T5", "--run-id", state.run_id, "--reason", "BLOCKED_EXTERNAL: Fresh Reviewer unavailable"],
    )
    assert code == 0
    assert blocked["run_stop_reason"]["code"] == Status.BLOCKED_EXTERNAL.value
    pending = load_state(path, project_root=root)
    assert pending.status is Status.RUNNING
    assert pending.stop_reason and pending.stop_reason["code"] == Status.BLOCKED_EXTERNAL.value

    code, checkpoint = _call(
        capsys,
        ["--root", str(root), "checkpoint", "create", "--run-id", state.run_id, "--next-action", "retry or obtain owner-approved substitute review"],
    )
    assert code == 0
    assert checkpoint["status"] == Status.BLOCKED_EXTERNAL.value
    stopped = load_state(path, project_root=root)
    assert stopped.status is Status.BLOCKED_EXTERNAL
    data = json.loads(Path(str(checkpoint["checkpoint"])).read_text(encoding="utf-8"))
    assert data["stop_reason"]["code"] == Status.BLOCKED_EXTERNAL.value


def test_verification_external_blocked_is_first_class_stop() -> None:
    decision = evaluate_stop(StopSignals(verification_external_blocked=True))
    assert decision.should_stop is True
    assert decision.status is Status.VERIFICATION_EXTERNAL_BLOCKED


def test_init_does_not_mutate_gitignore_when_info_exclude_already_ignores_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    exclude = root / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text(encoding="utf-8") + "\n.stackmarshal/\n", encoding="utf-8")

    code, initialized = _call(capsys, ["--root", str(root), "init"])
    assert code == 0
    assert initialized["preexisting_ignore"] is True
    assert initialized["gitignore_mutated"] is False
    assert not (root / ".gitignore").exists()


def test_cli_forces_utf8_evidence_even_with_legacy_stdio_encoding(tmp_path: Path) -> None:
    root = tmp_path / "utf8-project"
    root.mkdir()
    state_home = tmp_path / "user-state"
    env = os.environ.copy()
    env["STACKMARSHAL_STATE_HOME"] = str(state_home)
    env["PYTHONIOENCODING"] = "cp932"

    initialized = subprocess.run(
        [sys.executable, "-m", "stackmarshal.cli", "--root", str(root), "init"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr.decode("utf-8", errors="replace")

    invocation = "StackMarshalを使って日本語の証拠を実装して"
    started = subprocess.run(
        [sys.executable, "-m", "stackmarshal.cli", "--root", str(root), "start", "--invocation", invocation],
        env=env,
        capture_output=True,
        check=False,
    )
    assert started.returncode == 0, started.stderr.decode("utf-8", errors="replace")
    payload = json.loads(started.stdout.decode("utf-8"))
    state = json.loads(Path(payload["state"]).read_text(encoding="utf-8"))
    assert state["invocation"]["raw_text"] == invocation


def test_shadowed_launcher_cleanup_requires_high_confidence_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    managed_root = tmp_path / "managed"
    managed = managed_root / "bin" / ("stackmarshal.cmd" if os.name == "nt" else "stackmarshal")
    managed.parent.mkdir(parents=True)
    managed.write_text("managed", encoding="utf-8")
    stale = tmp_path / "python" / "Scripts" / "stackmarshal.exe"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"legacy")
    unknown = tmp_path / "other" / "stackmarshal.exe"
    unknown.parent.mkdir(parents=True)
    unknown.write_bytes(b"unknown")

    monkeypatch.setattr(cli_module, "_default_managed_install_root", lambda: managed_root)
    monkeypatch.setattr(cli_module.shutil, "which", lambda name: str(managed))
    monkeypatch.setattr(
        cli_module,
        "_path_stackmarshal_candidates",
        lambda: [
            {"path": str(managed), "version": __version__, "metadata_versions": []},
            {"path": str(stale), "version": None, "metadata_versions": ["1.0.0"]},
            {"path": str(unknown), "version": None, "metadata_versions": []},
        ],
    )

    removed, skipped = cli_module._remove_proven_shadowed_launchers()
    assert str(stale) in removed
    assert not stale.exists()
    assert unknown.exists()
    assert {item["path"]: item["reason"] for item in skipped}[str(unknown)] == "stackmarshal_provenance_unverified"


def test_migrate_dry_run_preserves_legacy_bytes_and_reports_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    run_id = "20260101-000000-0123abcd"
    legacy_dir = root / ".stackmarshal" / "runs" / run_id
    legacy_dir.mkdir(parents=True)
    legacy = legacy_dir / "run.json"
    original = b'{"schema_version":"1.0","run_id":"20260101-000000-0123abcd"}\n'
    legacy.write_bytes(original)

    code, result = _call(capsys, ["--root", str(root), "migrate", "--dry-run"])
    assert code == 0
    assert result["migrated"] is False
    assert result["dry_run"] is True
    assert legacy.read_bytes() == original
    assert result["moves"]


def test_migrate_no_legacy_is_noop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    code, result = _call(capsys, ["--root", str(root), "migrate"])
    assert code == 0
    assert result == {
        "migrated": False,
        "legacy_paths": [],
        "archive": None,
        "reason": "no_legacy_unsigned_state",
    }


def test_resume_rejects_non_resumable_terminal_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    path, state = _state_at(root)
    state.status = Status.UNSAFE_DEPENDENCY
    state.progress["resume_phase"] = Phase.VERIFICATION.value
    save_state(state, path)
    create_checkpoint(state, path.parent, next_action="start a new safe run")

    code, error = _call(capsys, ["--root", str(root), "resume", state.run_id])
    assert code == EXIT_INVALID_INPUT
    assert "not resumable" in str(error["error"])


def test_resume_rejects_competing_running_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    path, stopped = _state_at(root)
    stopped.status = Status.CHECKPOINT_READY
    stopped.progress["resume_phase"] = Phase.VERIFICATION.value
    save_state(stopped, path)
    create_checkpoint(stopped, path.parent, next_action="continue")

    other = create_run(root, "Use StackMarshal for another task", Mode.BUILD, default_config())
    other_path = root / ".stackmarshal" / "runs" / other.run_id / "run.json"
    save_state(other, other_path)

    code, error = _call(capsys, ["--root", str(root), "resume", stopped.run_id])
    assert code == EXIT_INVALID_INPUT
    assert other.run_id in str(error["error"])


def test_resume_rejects_checkpoint_from_another_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    path, stopped = _state_at(root)
    stopped.status = Status.CHECKPOINT_READY
    stopped.progress["resume_phase"] = Phase.VERIFICATION.value
    save_state(stopped, path)

    other = create_run(root, "Use StackMarshal for another task", Mode.BUILD, default_config())
    other.status = Status.CHECKPOINT_READY
    other.progress["resume_phase"] = Phase.VERIFICATION.value
    other_checkpoint, _ = create_checkpoint(
        other, root / ".stackmarshal" / "runs" / other.run_id, next_action="continue other"
    )

    code, error = _call(
        capsys,
        ["--root", str(root), "resume", stopped.run_id, "--file", str(other_checkpoint)],
    )
    assert code == EXIT_INVALID_INPUT
    assert "run id does not match" in str(error["error"]).lower()


def test_resume_phase_falls_back_to_signed_phase_snapshot_for_older_checkpoint_state(
    tmp_path: Path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    state = create_run(root, "Use StackMarshal to implement this", Mode.BUILD, default_config())
    state.status = Status.CHECKPOINT_READY
    state.phase = Phase.CHECKPOINTING
    state.progress["phase_snapshots"] = {
        Phase.IMPLEMENTATION.value: {"workspace_fingerprint": "old"},
        Phase.VERIFICATION.value: {"workspace_fingerprint": "verified"},
    }
    phase = cli_module._resume_phase_from_checkpoint({"resume_phase": None}, state)
    assert phase is Phase.VERIFICATION


def test_repair_reuses_managed_pin_and_reports_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    managed = {
        "root": str(tmp_path / "managed"),
        "version": __version__,
        "launcher": str(tmp_path / "managed" / "bin" / "stackmarshal.cmd"),
        "state_error": None,
    }
    monkeypatch.setattr(
        cli_module,
        "_pin_status_payload",
        lambda: {"managed_install": managed},
    )
    calls: list[tuple[str, bool, bool, bool, bool]] = []

    def fake_install_pin(
        target: str,
        *,
        assume_yes: bool,
        force: bool,
        allow_downgrade: bool,
        no_path: bool,
    ) -> str:
        calls.append((target, assume_yes, force, allow_downgrade, no_path))
        return target

    monkeypatch.setattr(cli_module, "install_pin", fake_install_pin)
    monkeypatch.setattr(cli_module, "_doctor_payload", lambda host: {"warnings": ["shadowed_stackmarshal_versions"]})
    monkeypatch.setattr(
        cli_module,
        "_remove_proven_shadowed_launchers",
        lambda: ([str(tmp_path / "stale.exe")], [{"path": "unknown.exe", "reason": "stackmarshal_provenance_unverified"}]),
    )

    code, result = _call(capsys, ["repair", "--yes", "--force", "--remove-shadowed"])
    assert code == 0
    assert calls == [(__version__, True, True, False, False)]
    assert result["repaired"] is True
    assert result["version"] == __version__
    assert result["removed_shadowed_launchers"] == [str(tmp_path / "stale.exe")]
    assert result["restart_codex"] is True


def test_repair_requires_managed_install(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "_pin_status_payload", lambda: {"managed_install": {"version": None}})
    code, result = _call(capsys, ["repair"])
    assert code == EXIT_INVALID_INPUT
    assert "pin latest" in str(result["error"])
