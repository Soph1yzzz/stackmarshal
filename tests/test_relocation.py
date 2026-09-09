from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from stackmarshal.cli import EXIT_INVALID_INPUT, main
from stackmarshal.hostwrite import pending_plan_path
from stackmarshal.integrity import verify_record
from stackmarshal.state import load_state


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, Any]]:
    code = main(argv)
    captured = capsys.readouterr()
    text = captured.out.strip() or captured.err.strip()
    return code, json.loads(text)


def _init_run(capsys: pytest.CaptureFixture[str], root: Path) -> str:
    code, initialized = _call(capsys, ["--root", str(root), "init"])
    assert code == 0 and initialized["initialized"] is True
    code, started = _call(
        capsys,
        ["--root", str(root), "start", "--invocation", "$stackmarshal build relocation contract"],
    )
    assert code == 0 and started["started"] is True
    return str(started["run_id"])


def _apply_host_plan(root: Path, payload: dict[str, Any]) -> str:
    plan = payload["plan"]
    verify_record(plan)
    for operation in plan["operations"]:
        target = root / str(operation["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if operation["operation"] == "write_text":
            expected = operation["expected_preimage_sha256"]
            if expected is None:
                assert not target.exists()
            else:
                assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
            target.write_bytes(str(operation["content"]).encode("utf-8"))
        elif operation["operation"] == "append_text":
            expected = operation["expected_preimage_sha256"]
            if expected is None:
                assert not target.exists()
            else:
                assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
            with target.open("ab") as handle:
                handle.write(str(operation["append_content"]).encode("utf-8"))
        else:
            raise AssertionError(operation["operation"])
        assert hashlib.sha256(target.read_bytes()).hexdigest() == operation["content_sha256"]
    return str(plan["plan_id"])


def test_signed_relocation_preserves_run_and_keeps_git_bootstrap_distinct(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "product.txt").write_text("same deliverable\n", encoding="utf-8")
    run_id = _init_run(capsys, source)

    code, prepared = _call(
        capsys,
        ["--root", str(source), "relocate", "prepare", "--to", str(target), "--run-id", run_id],
    )
    assert code == 0 and prepared["prepared"] is True
    permit_id = str(prepared["permit_id"])

    shutil.move(str(source), str(target))
    code, accepted = _call(
        capsys,
        ["--root", str(target), "relocate", "accept", "--permit-id", permit_id, "--run-id", run_id],
    )
    assert code == 0 and accepted["accepted"] is True
    assert accepted["reason"] == "workspace_relocation"
    state_path = target / ".stackmarshal" / "runs" / run_id / "run.json"
    state = load_state(state_path, project_root=target)
    assert state.run_id == run_id
    assert Path(state.project.root) == target.resolve()
    events_path = state_path.with_name("events.jsonl")
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert any(item["payload"].get("reason") == "workspace_relocation" for item in events)

    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True, text=True)
    code, moved = _call(
        capsys,
        ["--root", str(target), "state", "transition", "INTENT_NORMALIZATION", "--run-id", run_id],
    )
    assert code == 0 and moved["phase"] == "INTENT_NORMALIZATION"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    reasons = [item["payload"].get("reason") for item in events if item["event_type"] == "project_identity_migrated"]
    assert "workspace_relocation" in reasons
    assert "workspace_repository_bootstrap" in reasons


def test_relocation_accept_is_host_plannable_and_fingerprint_bound(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "product.txt").write_text("unchanged\n", encoding="utf-8")
    run_id = _init_run(capsys, source)
    code, prepared = _call(
        capsys,
        ["--root", str(source), "relocate", "prepare", "--to", str(target), "--run-id", run_id],
    )
    assert code == 0
    permit_id = str(prepared["permit_id"])
    shutil.move(str(source), str(target))

    code, planned = _call(
        capsys,
        [
            "--root",
            str(target),
            "--write-mode",
            "host",
            "relocate",
            "accept",
            "--permit-id",
            permit_id,
            "--run-id",
            run_id,
        ],
    )
    assert code == 0 and planned["host_write"] is True
    state_path = target / ".stackmarshal" / "runs" / run_id / "run.json"
    before = load_state(state_path, project_root=target)
    assert Path(before.project.root) != target.resolve()
    plan_id = _apply_host_plan(target, planned)
    code, ack = _call(capsys, ["--root", str(target), "host-write", "ack", "--plan-id", plan_id])
    assert code == 0 and ack["acknowledged"] is True
    assert not pending_plan_path(target).exists()
    after = load_state(state_path, project_root=target)
    assert Path(after.project.root) == target.resolve()


def test_relocation_migrates_signed_checkpoint_for_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "product.txt").write_text("checkpointed\n", encoding="utf-8")
    run_id = _init_run(capsys, source)
    code, checkpointed = _call(
        capsys,
        [
            "--root",
            str(source),
            "checkpoint",
            "create",
            "--run-id",
            run_id,
            "--next-action",
            "move workspace then resume",
        ],
    )
    assert code == 0 and checkpointed["succeeded"] is True

    code, prepared = _call(
        capsys,
        ["--root", str(source), "relocate", "prepare", "--to", str(target), "--run-id", run_id],
    )
    assert code == 0
    shutil.move(str(source), str(target))
    code, accepted = _call(
        capsys,
        [
            "--root",
            str(target),
            "relocate",
            "accept",
            "--permit-id",
            str(prepared["permit_id"]),
            "--run-id",
            run_id,
        ],
    )
    assert code == 0 and accepted["accepted"] is True

    code, inspected = _call(
        capsys,
        ["--root", str(target), "resume", "inspect", "--run-id", run_id],
    )
    assert code == 0
    assert inspected["run_id"] == run_id
    assert inspected["project_identity"] == accepted["project_identity"]
    checkpoint_md = target / ".stackmarshal" / "runs" / run_id / "checkpoint.md"
    assert f"- Project: `{target.resolve()}`" in checkpoint_md.read_text(encoding="utf-8")

    code, resumed = _call(
        capsys,
        ["--root", str(target), "resume", run_id, "--reason", "workspace relocation completed"],
    )
    assert code == 0 and resumed["resumed"] is True
    assert resumed["run_id"] == run_id


def test_relocation_rejects_workspace_content_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "product.txt").write_text("before\n", encoding="utf-8")
    run_id = _init_run(capsys, source)
    code, prepared = _call(
        capsys,
        ["--root", str(source), "relocate", "prepare", "--to", str(target), "--run-id", run_id],
    )
    assert code == 0
    shutil.move(str(source), str(target))
    (target / "product.txt").write_text("after\n", encoding="utf-8")
    code, rejected = _call(
        capsys,
        [
            "--root",
            str(target),
            "relocate",
            "accept",
            "--permit-id",
            str(prepared["permit_id"]),
            "--run-id",
            run_id,
        ],
    )
    assert code == EXIT_INVALID_INPUT
    assert "fingerprint changed" in rejected["error"].casefold()
