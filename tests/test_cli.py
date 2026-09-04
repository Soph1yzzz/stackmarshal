from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from stackmarshal.cli import (
    EXIT_BUDGET,
    EXIT_COMPLETE,
    EXIT_INVALID_INPUT,
    EXIT_INVALID_STATE,
    EXIT_UNSAFE,
    main,
)
from stackmarshal.constants import Phase, Status
from stackmarshal.lock import sha256_file
from stackmarshal.state import load_state, save_state


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, object]]:
    code = main(argv)
    captured = capsys.readouterr()
    text = captured.out.strip() or captured.err.strip()
    return code, json.loads(text)


def _init_and_start(root: Path, capsys: pytest.CaptureFixture[str]) -> str:
    code, payload = _call(capsys, ["--root", str(root), "init"])
    assert code == 0 and payload["initialized"] is True
    code, payload = _call(
        capsys,
        ["--root", str(root), "start", "--invocation", "Use StackMarshal to build it"],
    )
    assert code == 0 and payload["started"] is True
    return str(payload["run_id"])


def test_cli_init_start_show_audit_and_invocation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _init_and_start(root, capsys)
    assert (root / ".stackmarshal" / "config.toml").exists()
    assert ".stackmarshal/runs/" in (root / ".gitignore").read_text(encoding="utf-8")

    # init is idempotent and does not duplicate the marker
    _call(capsys, ["--root", str(root), "init"])
    lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines.count(".stackmarshal/runs/") == 1

    code, shown = _call(capsys, ["--root", str(root), "state", "show", "--run-id", run_id])
    assert code == 0
    assert shown["state"]["run_id"] == run_id  # type: ignore[index]

    audit_path = root / "audit.json"
    code, audit = _call(capsys, ["--root", str(root), "audit", "--output", str(audit_path)])
    assert code == 0 and Path(str(audit["written"])).exists()

    code, invoked = _call(capsys, ["invocation", "StackMarshalで調べて"])
    assert code == 0 and invoked == {"triggered": True, "mode": "research"}
    code, invoked = _call(capsys, ["invocation", "StackMarshalとは？"])
    assert code == EXIT_INVALID_INPUT and invoked["triggered"] is False


def test_cli_rejects_implicit_and_supports_budget_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _call(capsys, ["--root", str(root), "init"])
    code, payload = _call(
        capsys, ["--root", str(root), "start", "--invocation", "Implement this feature"]
    )
    assert code == EXIT_INVALID_INPUT and payload["started"] is False

    code, payload = _call(
        capsys,
        [
            "--root",
            str(root),
            "start",
            "--invocation",
            "$stackmarshal prepare",
            "--mode",
            "prepare",
            "--budget",
            "quick",
        ],
    )
    assert code == 0
    state = load_state(root / ".stackmarshal" / "runs" / str(payload["run_id"]) / "run.json")
    assert state.mode.value == "prepare"
    assert state.budget.profile == "quick"


def test_explicit_deep_budget_bypasses_repository_budget_profile(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _call(capsys, ["--root", str(root), "init"])
    (root / ".stackmarshal" / "config.toml").write_text('budget_profile = "deep"\n', encoding="utf-8")

    code, payload = _call(
        capsys,
        [
            "--root",
            str(root),
            "start",
            "--invocation",
            "$stackmarshal build explicit deep budget",
            "--budget",
            "deep",
        ],
    )
    assert code == 0
    state = load_state(root / ".stackmarshal" / "runs" / str(payload["run_id"]) / "run.json")
    assert state.budget.profile == "deep"
    assert state.budget.limits["tool_calls"] == 220


def test_cli_full_transition_report_and_terminal_guard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _call(capsys, ["--root", str(root), "init"])
    code, started = _call(
        capsys,
        [
            "--root",
            str(root),
            "start",
            "--invocation",
            "$stackmarshal prepare",
            "--mode",
            "prepare",
        ],
    )
    assert code == 0
    run_id = str(started["run_id"])
    path = root / ".stackmarshal" / "runs" / run_id / "run.json"
    phases = [
        Phase.INTENT_NORMALIZATION,
        Phase.ENVIRONMENT_AUDIT,
        Phase.RESEARCH_GATE,
        Phase.CAPABILITY_MAPPING,
        Phase.ARCHITECTURE_FREEZE,
        Phase.TASK_GRAPH,
        Phase.COMPLETE,
    ]
    for phase in phases:
        code, payload = _call(
            capsys,
            ["--root", str(root), "state", "transition", phase.value, "--run-id", run_id],
        )
        assert payload["phase"] == phase.value
    assert code == EXIT_COMPLETE

    code, report = _call(capsys, ["--root", str(root), "report", "--run-id", run_id])
    assert code == EXIT_COMPLETE
    assert Path(str(report["report"])).read_text(encoding="utf-8").startswith("# StackMarshal")

    code = main(
        ["--root", str(root), "state", "transition", Phase.STOPPED.value, "--run-id", run_id]
    )
    error = json.loads(capsys.readouterr().err)
    assert code == EXIT_INVALID_INPUT
    assert "terminal run" in error["error"]
    assert load_state(path).status is Status.COMPLETE


def test_cli_budget_candidate_failure_progress_and_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _init_and_start(root, capsys)
    state_path = root / ".stackmarshal" / "runs" / run_id / "run.json"

    code, budget = _call(capsys, ["--root", str(root), "budget", "check", "--run-id", run_id])
    assert code == 0 and budget["valid"] is True
    state = load_state(state_path)
    state.budget.used["tool_calls"] = state.budget.limits["tool_calls"] + 1
    save_state(state, state_path)
    code, budget = _call(capsys, ["--root", str(root), "budget", "check", "--run-id", run_id])
    assert code == EXIT_BUDGET and budget["valid"] is False

    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        json.dumps(
            {
                "id": "safe",
                "kind": "library",
                "source": {},
                "scores": {
                    "requirement_fit": 1,
                    "maintenance_health": 1,
                    "security_posture": 1,
                    "architecture_quality": 1,
                    "license_compatibility": 1,
                    "platform_support": 1,
                    "integration_cost": 1,
                    "documentation": 1,
                },
                "risks": [],
                "decision": "selected",
            }
        ),
        encoding="utf-8",
    )
    code, score = _call(capsys, ["candidate", "score", str(candidate_path)])
    assert code == 0 and score["total"] == 100.0
    code, valid = _call(capsys, ["validate", str(candidate_path), "--kind", "candidate"])
    assert code == 0 and valid["valid"] is True

    failure_path = tmp_path / "failure.json"
    failure_path.write_text(json.dumps({"message": "token=secret error 12"}), encoding="utf-8")
    code, fp = _call(capsys, ["failure", "fingerprint", str(failure_path)])
    assert code == 0 and len(str(fp["fingerprint"])) == 64

    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(json.dumps({"incomplete_tasks": 2}), encoding="utf-8")
    after.write_text(json.dumps({"incomplete_tasks": 1}), encoding="utf-8")
    code, progress = _call(
        capsys, ["progress", "evaluate", str(after), "--previous", str(before)]
    )
    assert code == 0 and progress["improved"] is True
    code, progress = _call(capsys, ["progress", "evaluate", str(after)])
    assert code == 0 and progress["improved"] is True

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    code, invalid = _call(capsys, ["validate", str(malformed)])
    assert code == EXIT_INVALID_STATE and invalid["valid"] is False


def test_cli_lock_checkpoint_resume_stop_and_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "seed.txt").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
    run_id = _init_and_start(root, capsys)

    artifact = root / "artifact.txt"
    artifact.write_text("safe", encoding="utf-8")
    lock_path = root / "lock.json"
    entry = {
        "kind": "library",
        "id": "example",
        "source": "https://example.invalid",
        "version": "1.0",
        "commit": None,
        "sha256": sha256_file(artifact),
        "license": "MIT",
        "permissions": [],
        "verification": [],
        "selected_reason": "test",
        "artifact": "artifact.txt",
    }
    lock_path.write_text(json.dumps({"schema_version": "1.0", "entries": [entry]}), encoding="utf-8")
    code, verified = _call(capsys, ["--root", str(root), "lock", "verify", str(lock_path)])
    assert code == 0 and verified["valid"] is True
    entry["sha256"] = "0" * 64
    lock_path.write_text(json.dumps({"schema_version": "1.0", "entries": [entry]}), encoding="utf-8")
    code, verified = _call(capsys, ["--root", str(root), "lock", "verify", str(lock_path)])
    assert code == EXIT_UNSAFE and verified["valid"] is False

    code, checkpoint = _call(
        capsys,
        [
            "--root",
            str(root),
            "checkpoint",
            "create",
            "--run-id",
            run_id,
            "--next-action",
            "Continue verification",
            "--do-not-repeat",
            "bad approach",
        ],
    )
    assert code == 0 and checkpoint["succeeded"] is True and Path(str(checkpoint["checkpoint"])).exists()
    code, inspected = _call(
        capsys,
        ["--root", str(root), "resume", "inspect", "--file", str(checkpoint["checkpoint"])],
    )
    assert code == 0 and inspected["next_action"] == "Continue verification"

    # Use a second run to test formal stop from RUNNING.
    code, payload = _call(
        capsys,
        ["--root", str(root), "start", "--invocation", "Use StackMarshal to build"],
    )
    second = str(payload["run_id"])
    code, stopped = _call(
        capsys,
        [
            "--root",
            str(root),
            "stop",
            Status.UNSAFE_DEPENDENCY.value,
            "--run-id",
            second,
            "--reason",
            "Untrusted binary",
            "--next-action",
            "Choose a source build",
        ],
    )
    assert code == EXIT_UNSAFE and stopped["status"] == Status.UNSAFE_DEPENDENCY.value

    # No run and non-object JSON both produce bounded input errors.
    empty = tmp_path / "empty"
    empty.mkdir()
    code = main(["--root", str(empty), "state", "show"])
    assert code == EXIT_INVALID_INPUT
    assert "No StackMarshal run" in json.loads(capsys.readouterr().err)["error"]
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    code = main(["candidate", "score", str(array)])
    assert code == EXIT_INVALID_INPUT
    assert "Expected a JSON object" in json.loads(capsys.readouterr().err)["error"]
