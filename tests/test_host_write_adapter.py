from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

import stackmarshal.hostwrite as hostwrite
from stackmarshal.cli import EXIT_COMPLETE, EXIT_INVALID_INPUT, EXIT_INVALID_STATE, main
from stackmarshal.hostwrite import pending_plan_path
from stackmarshal.integrity import sign_record, verify_record
from stackmarshal.state import Phase, load_state


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, Any]]:
    code = main(argv)
    captured = capsys.readouterr()
    text = captured.out.strip() or captured.err.strip()
    return code, json.loads(text)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _apply_host_plan(root: Path, payload: dict[str, Any]) -> str:
    assert payload["host_write"] is True
    plan = payload["plan"]
    verify_record(plan)
    plan_id = str(plan["plan_id"])
    for operation in plan["operations"]:
        assert operation["operation"] == "write_text"
        target = root / str(operation["path"])
        expected = operation["expected_preimage"]
        if expected is None:
            assert not target.exists()
        else:
            assert target.read_text(encoding="utf-8") == expected
            assert hashlib.sha256(target.read_bytes()).hexdigest() == operation["expected_preimage_sha256"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(str(operation["content"]).encode("utf-8"))
        assert hashlib.sha256(target.read_bytes()).hexdigest() == operation["content_sha256"]
    return plan_id


def _host_mutation(
    capsys: pytest.CaptureFixture[str],
    root: Path,
    *command: str,
    expected_code: int = 0,
) -> dict[str, Any]:
    code, payload = _call(capsys, ["--root", str(root), "--write-mode", "host", *command])
    assert code == expected_code, payload
    assert payload["host_write"] is True
    plan_id = str(payload["plan_id"])
    code, checked = _call(
        capsys,
        ["--root", str(root), "host-write", "check", "--plan-id", plan_id],
    )
    assert code == 0
    assert checked["ready_to_apply"] is True
    assert _apply_host_plan(root, payload) == plan_id
    code, ack = _call(
        capsys,
        ["--root", str(root), "host-write", "ack", "--plan-id", plan_id],
    )
    assert code == 0
    assert ack["acknowledged"] is True
    assert not pending_plan_path(root).exists()
    return payload


def _move(capsys: pytest.CaptureFixture[str], root: Path, run_id: str, phase: Phase) -> None:
    _host_mutation(
        capsys,
        root,
        "state",
        "transition",
        phase.value,
        "--run-id",
        run_id,
        expected_code=EXIT_COMPLETE if phase is Phase.COMPLETE else 0,
    )


def test_host_mode_init_and_start_do_not_write_project_before_host_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    code, planned = _call(capsys, ["--root", str(root), "--write-mode", "host", "init"])
    assert code == 0
    assert planned["host_write"] is True
    assert not (root / ".stackmarshal").exists()
    assert not (root / ".gitignore").exists()
    paths = {operation["path"] for operation in planned["plan"]["operations"]}
    assert ".stackmarshal/config.toml" in paths
    assert ".gitignore" in paths

    plan_id = _apply_host_plan(root, planned)
    code, ack = _call(capsys, ["--root", str(root), "host-write", "ack", "--plan-id", plan_id])
    assert code == 0 and ack["acknowledged"] is True

    code, started = _call(
        capsys,
        [
            "--root",
            str(root),
            "--write-mode",
            "host",
            "start",
            "--invocation",
            "$stackmarshal build host transport contract",
        ],
    )
    assert code == 0
    run_id = str(started["command_result"]["run_id"])
    run_path = root / ".stackmarshal" / "runs" / run_id / "run.json"
    assert not run_path.exists()
    paths = {operation["path"] for operation in started["plan"]["operations"]}
    assert f".stackmarshal/runs/{run_id}/run.json" in paths
    assert f".stackmarshal/runs/{run_id}/events.jsonl" in paths
    assert f".stackmarshal/runs/{run_id}/environment-audit.json" in paths

    plan_id = _apply_host_plan(root, started)
    code, ack = _call(capsys, ["--root", str(root), "host-write", "ack", "--plan-id", plan_id])
    assert code == 0 and ack["acknowledged"] is True
    assert load_state(run_path, project_root=root).run_id == run_id


def test_pending_plan_blocks_second_mutation_and_preimage_mismatch_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _host_mutation(capsys, root, "init")
    started = _host_mutation(
        capsys,
        root,
        "start",
        "--invocation",
        "$stackmarshal build pending-plan contract",
    )
    run_id = str(started["command_result"]["run_id"])

    code, planned = _call(
        capsys,
        [
            "--root",
            str(root),
            "--write-mode",
            "host",
            "state",
            "transition",
            Phase.INTENT_NORMALIZATION.value,
            "--run-id",
            run_id,
        ],
    )
    assert code == 0
    plan_id = str(planned["plan_id"])

    code, rejected = _call(
        capsys,
        [
            "--root",
            str(root),
            "--write-mode",
            "host",
            "activity",
            "record",
            "tool-call",
            "--run-id",
            run_id,
        ],
    )
    assert code == EXIT_INVALID_INPUT
    assert "still pending" in rejected["error"]

    run_path = root / ".stackmarshal" / "runs" / run_id / "run.json"
    original = run_path.read_text(encoding="utf-8")
    run_path.write_text(original + " ", encoding="utf-8")
    code, checked = _call(
        capsys,
        ["--root", str(root), "host-write", "check", "--plan-id", plan_id],
    )
    assert code == EXIT_INVALID_STATE
    assert any("preimage_hash_mismatch" in error for error in checked["errors"])
    run_path.write_text(original, encoding="utf-8")

    code, aborted = _call(
        capsys,
        [
            "--root",
            str(root),
            "host-write",
            "abort",
            "--plan-id",
            plan_id,
            "--reason",
            "test cleanup",
        ],
    )
    assert code == 0 and aborted["aborted"] is True


def test_host_plan_tamper_and_wrong_postimage_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    code, planned = _call(capsys, ["--root", str(root), "--write-mode", "host", "init"])
    assert code == 0
    plan_id = str(planned["plan_id"])
    pending = pending_plan_path(root)
    data = json.loads(pending.read_text(encoding="utf-8"))
    data["operations"][0]["content"] += "tampered"
    pending.write_text(json.dumps(data), encoding="utf-8")
    code, rejected = _call(
        capsys,
        ["--root", str(root), "host-write", "check", "--plan-id", plan_id],
    )
    assert code == EXIT_INVALID_INPUT
    assert "integrity" in rejected["error"].casefold()

    pending.unlink()
    code, planned = _call(capsys, ["--root", str(root), "--write-mode", "host", "init"])
    assert code == 0
    plan_id = _apply_host_plan(root, planned)
    first = root / str(planned["plan"]["operations"][0]["path"])
    first.write_bytes(b"wrong postimage\n")
    code, ack = _call(capsys, ["--root", str(root), "host-write", "ack", "--plan-id", plan_id])
    assert code == EXIT_INVALID_STATE
    assert ack["acknowledged"] is False
    assert any("postimage_hash_mismatch" in error for error in ack["errors"])


def test_host_mode_live_lifecycle_reaches_finalize_without_shell_project_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _host_mutation(capsys, root, "init")
    started = _host_mutation(
        capsys,
        root,
        "start",
        "--invocation",
        "$stackmarshal build host adapter live lifecycle",
    )
    run_id = str(started["command_result"]["run_id"])

    _move(capsys, root, run_id, Phase.INTENT_NORMALIZATION)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "host@example.invalid")
    _git(root, "config", "user.name", "Host Adapter Contract")
    _move(capsys, root, run_id, Phase.ENVIRONMENT_AUDIT)
    for phase in (
        Phase.RESEARCH_GATE,
        Phase.CAPABILITY_MAPPING,
        Phase.ARCHITECTURE_FREEZE,
        Phase.TASK_GRAPH,
    ):
        _move(capsys, root, run_id, phase)

    _host_mutation(
        capsys,
        root,
        "task",
        "add",
        "implement",
        "--run-id",
        run_id,
        "--summary",
        "Create deliverable",
        "--acceptance",
        "deliverable evidence exists",
    )
    _host_mutation(
        capsys,
        root,
        "task",
        "add",
        "verify",
        "--run-id",
        run_id,
        "--summary",
        "Verify deliverable",
        "--acceptance",
        "verification evidence exists",
    )
    _move(capsys, root, run_id, Phase.IMPLEMENTATION)
    _host_mutation(capsys, root, "task", "start", "implement", "--run-id", run_id)
    _host_mutation(
        capsys,
        root,
        "activity",
        "record",
        "tool-call",
        "--run-id",
        run_id,
        "--amount",
        "4",
        "--detail",
        "bounded implementation batch",
    )
    deliverable = root / "deliverable.txt"
    deliverable.write_text("host adapter lifecycle\n", encoding="utf-8")
    _host_mutation(
        capsys,
        root,
        "activity",
        "record",
        "implementation",
        "--run-id",
        run_id,
        "--detail",
        "deliverable created",
    )
    _host_mutation(
        capsys,
        root,
        "task",
        "complete",
        "implement",
        "--run-id",
        run_id,
        "--evidence",
        "deliverable.txt exists",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "host adapter implementation")

    _move(capsys, root, run_id, Phase.VERIFICATION)
    _host_mutation(capsys, root, "task", "start", "verify", "--run-id", run_id)
    _host_mutation(
        capsys,
        root,
        "activity",
        "record",
        "tool-call",
        "--run-id",
        run_id,
        "--amount",
        "2",
        "--detail",
        "bounded verification batch",
    )
    _host_mutation(capsys, root, "activity", "record", "verification", "--run-id", run_id)
    _host_mutation(
        capsys,
        root,
        "task",
        "complete",
        "verify",
        "--run-id",
        run_id,
        "--evidence",
        "deliverable content verified",
    )

    finalized = _host_mutation(capsys, root, "finalize", "--run-id", run_id)
    assert finalized["command_result"]["finalized"] is True
    state = load_state(root / ".stackmarshal" / "runs" / run_id / "run.json", project_root=root)
    assert isinstance(state.progress.get("finalization"), dict)


def test_signed_host_plan_rejects_path_escape_and_hash_inconsistency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    code, planned = _call(capsys, ["--root", str(root), "--write-mode", "host", "init"])
    assert code == 0
    plan_id = str(planned["plan_id"])
    pending = pending_plan_path(root)

    data = json.loads(pending.read_text(encoding="utf-8"))
    data["operations"][0]["path"] = "../escape.txt"
    pending.write_text(json.dumps(sign_record(data)), encoding="utf-8")
    code, rejected = _call(
        capsys,
        ["--root", str(root), "host-write", "check", "--plan-id", plan_id],
    )
    assert code == EXIT_INVALID_INPUT
    assert "unsafe host-write target" in rejected["error"].casefold()

    pending.unlink()
    code, planned = _call(capsys, ["--root", str(root), "--write-mode", "host", "init"])
    assert code == 0
    plan_id = str(planned["plan_id"])
    data = json.loads(pending.read_text(encoding="utf-8"))
    data["operations"][0]["content_sha256"] = "0" * 64
    pending.write_text(json.dumps(sign_record(data)), encoding="utf-8")
    code, rejected = _call(
        capsys,
        ["--root", str(root), "host-write", "check", "--plan-id", plan_id],
    )
    assert code == EXIT_INVALID_INPUT
    assert "content hash is inconsistent" in rejected["error"].casefold()


def test_host_plan_semantic_validator_rejects_malformed_contracts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    code, planned = _call(capsys, ["--root", str(root), "--write-mode", "host", "init"])
    assert code == 0
    base = json.loads(json.dumps(planned["plan"]))
    pending_plan_path(root).unlink()

    def rejected(mutator: Any, message: str) -> None:
        candidate = json.loads(json.dumps(base))
        mutator(candidate)
        with pytest.raises(hostwrite.HostWriteError, match=message):
            hostwrite._validate_plan_identity(root, candidate)

    rejected(lambda item: item.update(schema_version="9.9"), "Unsupported host-write plan schema")
    rejected(lambda item: item.update(project_root=str(tmp_path / "other")), "different workspace root")
    rejected(lambda item: item.update(project_identity="0" * 64), "Workspace identity changed")
    rejected(lambda item: item.update(plan_id=""), "missing plan_id")
    rejected(lambda item: item.update(operations=[]), "no operations")
    rejected(lambda item: item["operations"][0].update(operation="delete"), "unsupported operation")
    rejected(lambda item: item["operations"][0].update(content_sha256=7), "invalid text operation")
    rejected(
        lambda item: item["operations"].append(json.loads(json.dumps(item["operations"][0]))),
        "duplicate target",
    )
    rejected(
        lambda item: item["operations"][0].update(expected_preimage_sha256="1" * 64),
        "absent preimage has a hash",
    )
    rejected(
        lambda item: item["operations"][0].update(expected_preimage=7, expected_preimage_sha256="1" * 64),
        "preimage contract is invalid",
    )
    rejected(lambda item: item["operations"][0].update(path="dir\\escape.txt"), "Unsafe host-write target")
    rejected(lambda item: item["operations"][0].update(path="C:escape.txt"), "Unsafe host-write target")


def test_host_write_status_and_mode_boundaries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    code, status = _call(capsys, ["--root", str(root), "host-write", "status"])
    assert code == 0 and status == {"pending": False}

    code, planned = _call(capsys, ["--root", str(root), "--write-mode", "host", "init"])
    assert code == 0
    code, status = _call(capsys, ["--root", str(root), "host-write", "status"])
    assert code == 0
    assert status["pending"] is True
    assert status["plan_id"] == planned["plan_id"]

    code, wrong = _call(
        capsys,
        ["--root", str(root), "host-write", "ack", "--plan-id", "0" * 32],
    )
    assert code == EXIT_INVALID_INPUT
    assert "does not match" in wrong["error"]

    plan_id = str(planned["plan_id"])
    code, aborted = _call(
        capsys,
        ["--root", str(root), "host-write", "abort", "--plan-id", plan_id, "--reason", "boundary test"],
    )
    assert code == 0 and aborted["aborted"] is True

    for command in (["migrate"], ["pin", "1.1.6"], ["repair"]):
        code, rejected = _call(capsys, ["--root", str(root), "--write-mode", "host", *command])
        assert code == EXIT_INVALID_INPUT
        assert "error" in rejected


def test_host_write_missing_pending_and_unapplied_plan_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    for command in (
        ["host-write", "check", "--plan-id", "0" * 32],
        ["host-write", "ack", "--plan-id", "0" * 32],
        ["host-write", "abort", "--plan-id", "0" * 32, "--reason", "nothing pending"],
    ):
        code, rejected = _call(capsys, ["--root", str(root), *command])
        assert code == EXIT_INVALID_INPUT
        assert "No host-write plan is pending" in rejected["error"]

    code, planned = _call(capsys, ["--root", str(root), "--write-mode", "host", "init"])
    assert code == 0
    plan_id = str(planned["plan_id"])
    first_target = root / str(planned["plan"]["operations"][0]["path"])
    first_target.parent.mkdir(parents=True, exist_ok=True)
    first_target.write_bytes(b"appeared-after-plan\n")
    code, checked = _call(
        capsys,
        ["--root", str(root), "host-write", "check", "--plan-id", plan_id],
    )
    assert code == EXIT_INVALID_STATE
    assert any("preimage_expected_absent" in error for error in checked["errors"])
    first_target.unlink()
    code, ack = _call(capsys, ["--root", str(root), "host-write", "ack", "--plan-id", plan_id])
    assert code == EXIT_INVALID_STATE
    assert ack["acknowledged"] is False
    assert any("postimage_missing_or_unsafe" in error for error in ack["errors"])

    pending = pending_plan_path(root)
    pending.write_text("{not-json", encoding="utf-8")
    code, rejected = _call(capsys, ["--root", str(root), "host-write", "status"])
    assert code == EXIT_INVALID_INPUT
    assert "Could not read host-write record" in rejected["error"]


def test_direct_mode_remains_default_and_creates_no_host_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    code, initialized = _call(capsys, ["--root", str(root), "init"])
    assert code == 0
    assert initialized["initialized"] is True
    assert (root / ".stackmarshal" / "config.toml").is_file()
    assert not pending_plan_path(root).exists()
