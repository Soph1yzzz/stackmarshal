from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from stackmarshal.cli import EXIT_BUDGET, EXIT_COMPLETE, EXIT_INVALID_STATE, main
from stackmarshal.constants import Phase, __version__
from stackmarshal.state import load_state, project_info
from stackmarshal.taskgraph import load_task_graph


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, object]]:
    code = main(argv)
    captured = capsys.readouterr()
    text = captured.out.strip() or captured.err.strip()
    return code, json.loads(text)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _start(root: Path, capsys: pytest.CaptureFixture[str]) -> str:
    code, _ = _call(capsys, ["--root", str(root), "init"])
    assert code == 0
    code, payload = _call(
        capsys,
        ["--root", str(root), "start", "--invocation", "$stackmarshal build nextpatch test"],
    )
    assert code == 0
    return str(payload["run_id"])


def _transition(root: Path, run_id: str, phase: Phase, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    code, payload = _call(
        capsys,
        ["--root", str(root), "state", "transition", phase.value, "--run-id", run_id],
    )
    assert code in {0, EXIT_COMPLETE}
    return payload


def _to_task_graph(root: Path, run_id: str, capsys: pytest.CaptureFixture[str]) -> None:
    for phase in (
        Phase.INTENT_NORMALIZATION,
        Phase.ENVIRONMENT_AUDIT,
        Phase.RESEARCH_GATE,
        Phase.CAPABILITY_MAPPING,
        Phase.ARCHITECTURE_FREEZE,
        Phase.TASK_GRAPH,
    ):
        _transition(root, run_id, phase, capsys)


def test_nested_workspace_does_not_inherit_parent_repository(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    _git(parent, "init", "-q")
    _git(parent, "config", "user.email", "test@example.invalid")
    _git(parent, "config", "user.name", "Test")
    (parent / "tracked.txt").write_text("parent", encoding="utf-8")
    _git(parent, "add", "tracked.txt")
    _git(parent, "commit", "-qm", "parent")
    child = parent / "lab" / "fresh-project"
    child.mkdir(parents=True)

    info = project_info(child)
    assert info.repository_owned is False
    assert info.git_toplevel is None
    assert info.git_head is None
    assert info.repository_lineage == []
    assert info.dirty is False


def test_repository_bootstrap_migrates_one_authoritative_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    run_id = _start(root, capsys)
    _transition(root, run_id, Phase.INTENT_NORMALIZATION, capsys)

    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _transition(root, run_id, Phase.ENVIRONMENT_AUDIT, capsys)

    (root / "README.md").write_text("# fresh\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "bootstrap")
    _transition(root, run_id, Phase.RESEARCH_GATE, capsys)

    runs = list((root / ".stackmarshal" / "runs").glob("*/run.json"))
    assert len(runs) == 1
    state = load_state(runs[0])
    assert state.run_id == run_id
    assert state.project.repository_owned is True
    assert state.project.git_toplevel == str(root.resolve())
    assert state.project.repository_lineage
    events = (runs[0].with_name("events.jsonl")).read_text(encoding="utf-8")
    assert events.count("project_identity_migrated") == 2
    assert "workspace_repository_bootstrap" in events
    assert "repository_first_commit" in events


def test_second_authoritative_run_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    first = _start(root, capsys)
    code, payload = _call(
        capsys,
        ["--root", str(root), "start", "--invocation", "$stackmarshal build duplicate"],
    )
    assert code == EXIT_INVALID_STATE
    assert payload["reason"] == "authoritative_run_already_active"
    assert payload["run_id"] == first
    assert len(list((root / ".stackmarshal" / "runs").glob("*/run.json"))) == 1


def test_live_build_consumes_budget_syncs_tasks_and_completes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _start(root, capsys)
    _to_task_graph(root, run_id, capsys)

    for task_id, summary in (("impl", "Implement artifact"), ("verify", "Verify artifact")):
        code, payload = _call(
            capsys,
            [
                "--root",
                str(root),
                "task",
                "add",
                task_id,
                "--run-id",
                run_id,
                "--summary",
                summary,
                "--acceptance",
                f"{task_id} acceptance",
            ],
        )
        assert code == 0 and payload["added"] is True

    _transition(root, run_id, Phase.IMPLEMENTATION, capsys)
    code, _ = _call(
        capsys,
        ["--root", str(root), "task", "start", "impl", "--run-id", run_id],
    )
    assert code == 0
    code, budget = _call(
        capsys,
        [
            "--root",
            str(root),
            "activity",
            "record",
            "tool-call",
            "--run-id",
            run_id,
            "--amount",
            "3",
            "--detail",
            "three bounded implementation tool calls",
        ],
    )
    assert code == 0 and budget["budget"]["tool_calls"] == 3  # type: ignore[index]
    (root / "artifact.txt").write_text("implemented\n", encoding="utf-8")
    code, _ = _call(
        capsys,
        ["--root", str(root), "activity", "record", "implementation", "--run-id", run_id],
    )
    assert code == 0
    code, _ = _call(
        capsys,
        [
            "--root",
            str(root),
            "task",
            "complete",
            "impl",
            "--run-id",
            run_id,
            "--evidence",
            "artifact.txt created",
        ],
    )
    assert code == 0

    _transition(root, run_id, Phase.VERIFICATION, capsys)
    code, _ = _call(
        capsys,
        ["--root", str(root), "task", "start", "verify", "--run-id", run_id],
    )
    assert code == 0
    code, _ = _call(
        capsys,
        [
            "--root",
            str(root),
            "activity",
            "record",
            "tool-call",
            "--run-id",
            run_id,
            "--amount",
            "2",
            "--detail",
            "verification commands",
        ],
    )
    assert code == 0
    code, _ = _call(
        capsys,
        ["--root", str(root), "activity", "record", "verification", "--run-id", run_id],
    )
    assert code == 0
    code, _ = _call(
        capsys,
        [
            "--root",
            str(root),
            "task",
            "complete",
            "verify",
            "--run-id",
            run_id,
            "--evidence",
            "verification passed",
        ],
    )
    assert code == 0

    code, finalized = _call(
        capsys,
        ["--root", str(root), "finalize", "--run-id", run_id],
    )
    assert code == 0 and finalized["finalized"] is True

    code, payload = _call(
        capsys,
        ["--root", str(root), "state", "transition", Phase.COMPLETE.value, "--run-id", run_id],
    )
    assert code == EXIT_COMPLETE
    assert payload["status"] == "COMPLETE"

    state = load_state(root / ".stackmarshal" / "runs" / run_id / "run.json")
    assert state.budget.used["tool_calls"] == 5
    assert state.budget.used["attempts_per_task"] == 1
    assert state.progress["completion_gate"]["validated"] is True
    assert state.progress["completion_gate"]["finalization"] == "sealed"
    assert state.progress["terminal_seal"]["workspace_fingerprint"]
    assert state.progress["finalization"]["files"]["environment-audit.json"]
    snapshots = state.progress["phase_snapshots"]
    assert snapshots["IMPLEMENTATION"]["workspace_fingerprint"] != snapshots["VERIFICATION"]["workspace_fingerprint"]
    graph = load_task_graph(root, required=True)
    assert {task["status"] for task in graph["tasks"]} == {"done"}
    markdown = (root / ".stackmarshal" / "project" / "task-graph.md").read_text(encoding="utf-8")
    assert "- [x] `impl`" in markdown and "- [x] `verify`" in markdown


def test_complete_rejects_replayed_or_stale_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _start(root, capsys)
    _to_task_graph(root, run_id, capsys)
    _call(
        capsys,
        [
            "--root",
            str(root),
            "task",
            "add",
            "impl",
            "--run-id",
            run_id,
            "--summary",
            "Still pending",
        ],
    )
    _transition(root, run_id, Phase.IMPLEMENTATION, capsys)
    _transition(root, run_id, Phase.VERIFICATION, capsys)
    code, payload = _call(
        capsys,
        ["--root", str(root), "state", "transition", Phase.COMPLETE.value, "--run-id", run_id],
    )
    assert code == EXIT_INVALID_STATE
    errors = payload["errors"]
    assert any(str(item).startswith("mandatory_task_not_done:impl") for item in errors)  # type: ignore[union-attr]
    assert "missing_live_implementation_activity" in errors
    assert "missing_live_verification_activity" in errors
    assert "untouched_tool_call_budget" in errors
    assert "no_workspace_change_during_implementation" in errors
    assert "missing_finalization" in errors


def test_activity_budget_exhaustion_formally_stops_and_checkpoints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("STACKMARSHAL_STATE_HOME", str((tmp_path / "state-home").resolve()))
    code, _ = _call(capsys, ["--root", str(root), "init"])
    assert code == 0
    code, started = _call(
        capsys,
        [
            "--root",
            str(root),
            "start",
            "--invocation",
            "$stackmarshal build budget stop",
            "--budget",
            "quick",
        ],
    )
    assert code == 0
    run_id = str(started["run_id"])
    code, payload = _call(
        capsys,
        [
            "--root",
            str(root),
            "activity",
            "record",
            "tool-call",
            "--run-id",
            run_id,
            "--amount",
            "51",
        ],
    )
    assert code == EXIT_BUDGET
    assert payload["status"] == "BUDGET_EXHAUSTED"
    assert payload["counter"] == "tool_calls"
    checkpoint = Path(str(payload["checkpoint"]))
    assert checkpoint.exists()
    state = load_state(root / ".stackmarshal" / "runs" / run_id / "run.json")
    assert state.status.value == "BUDGET_EXHAUSTED"
    assert state.budget.used.get("tool_calls", 0) == 0
    assert state.stop_reason is not None
    assert state.stop_reason["details"]["attempted"] == 51
    events = checkpoint.with_name("events.jsonl").read_text(encoding="utf-8")
    assert "formal_stop" in events


def test_doctor_detects_stale_host_skill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex"
    skill = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f'---\nmetadata:\n  version: "{__version__}"\n---\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    code, payload = _call(capsys, ["doctor", "--host-skill-version", __version__])
    assert code == 0 and payload["ready"] is True
    code, payload = _call(capsys, ["doctor", "--host-skill-version", "0.0.0"])
    assert code == EXIT_INVALID_STATE
    assert payload["restart_required"] is True
