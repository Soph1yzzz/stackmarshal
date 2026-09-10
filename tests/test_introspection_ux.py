from __future__ import annotations

import json
from pathlib import Path

import pytest

import stackmarshal.cli as cli_module
from stackmarshal.cli import EXIT_BUDGET, EXIT_INVALID_INPUT, main
from stackmarshal.constants import Phase, Status
from stackmarshal.state import load_state
from stackmarshal.taskgraph import load_task_graph


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, object]]:
    code = main(argv)
    captured = capsys.readouterr()
    text = captured.out.strip() or captured.err.strip()
    return code, json.loads(text)


def _start(root: Path, capsys: pytest.CaptureFixture[str]) -> str:
    code, initialized = _call(capsys, ["--root", str(root), "init"])
    assert code == 0 and initialized["initialized"] is True
    code, started = _call(
        capsys,
        ["--root", str(root), "start", "--invocation", "$stackmarshal build introspection contract"],
    )
    assert code == 0 and started["started"] is True
    return str(started["run_id"])


def _transition(capsys: pytest.CaptureFixture[str], root: Path, run_id: str, phase: Phase) -> None:
    code, payload = _call(
        capsys,
        ["--root", str(root), "state", "transition", phase.value, "--run-id", run_id],
    )
    assert code == 0, payload


def _to_task_graph(capsys: pytest.CaptureFixture[str], root: Path, run_id: str) -> None:
    for phase in (
        Phase.INTENT_NORMALIZATION,
        Phase.ENVIRONMENT_AUDIT,
        Phase.RESEARCH_GATE,
        Phase.CAPABILITY_MAPPING,
        Phase.ARCHITECTURE_FREEZE,
        Phase.TASK_GRAPH,
    ):
        _transition(capsys, root, run_id, phase)


def test_next_is_non_prescriptive_state_introspection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _start(root, capsys)
    run_path = root / ".stackmarshal" / "runs" / run_id / "run.json"
    events_path = run_path.with_name("events.jsonl")
    before_run = run_path.read_bytes()
    before_events = events_path.read_bytes()

    code, snapshot = _call(capsys, ["--root", str(root), "next", "--run-id", run_id])

    assert code == 0
    assert run_path.read_bytes() == before_run
    assert events_path.read_bytes() == before_events
    assert snapshot["policy"] == "introspection_only"
    assert snapshot["phase"] == Phase.INVOCATION_CHECK.value
    assert snapshot["status"] == "RUNNING"
    assert snapshot["legal_transitions"] == [Phase.INTENT_NORMALIZATION.value, Phase.STOPPED.value]
    assert snapshot["resumable"] is False
    assert isinstance(snapshot["completion_prerequisites"], list)
    rendered = json.dumps(snapshot, ensure_ascii=False).casefold()
    assert "stackmarshal " not in rendered
    assert "delete " not in rendered
    assert "execute " not in rendered


def test_next_surfaces_completion_diagnostic_without_prescribing_recovery(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _start(root, capsys)

    def blocked(*_args: object, **_kwargs: object) -> list[str]:
        raise ValueError("Workspace contains Windows reserved device name during fingerprint: NUL")

    monkeypatch.setattr(cli_module, "_completion_gate_errors", blocked)
    code, snapshot = _call(capsys, ["--root", str(root), "next", "--run-id", run_id])

    assert code == 0
    assert snapshot["completion_prerequisites"] == ["completion_diagnostic_blocked"]
    diagnostic = next(
        item
        for item in snapshot["blockers"]  # type: ignore[union-attr]
        if isinstance(item, dict) and item.get("kind") == "completion_diagnostic"
    )
    assert "reserved device name" in str(diagnostic["reason"])
    rendered = json.dumps(snapshot, ensure_ascii=False).casefold()
    assert "delete " not in rendered
    assert "remove " not in rendered


def test_next_exposes_resume_capability_without_recovery_script(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _start(root, capsys)
    code, checkpointed = _call(
        capsys,
        [
            "--root",
            str(root),
            "checkpoint",
            "create",
            "--run-id",
            run_id,
            "--next-action",
            "Resolve the external condition independently",
        ],
    )
    assert code == 0 and checkpointed["succeeded"] is True

    code, snapshot = _call(capsys, ["--root", str(root), "next", "--run-id", run_id])

    assert code == 0
    assert snapshot["resumable"] is True
    assert snapshot["legal_transitions"] == []
    assert any(
        isinstance(item, dict) and item.get("kind") == "terminal_status"
        for item in snapshot["blockers"]  # type: ignore[union-attr]
    )
    rendered = json.dumps(snapshot, ensure_ascii=False).casefold()
    assert "stackmarshal resume" not in rendered


def test_late_task_requires_replan_and_consumes_bounded_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _start(root, capsys)
    _to_task_graph(capsys, root, run_id)
    code, added = _call(
        capsys,
        [
            "--root",
            str(root),
            "task",
            "add",
            "initial",
            "--run-id",
            run_id,
            "--summary",
            "initial task",
            "--acceptance",
            "exists",
        ],
    )
    assert code == 0 and added["added"] is True
    _transition(capsys, root, run_id, Phase.IMPLEMENTATION)

    code, rejected = _call(
        capsys,
        [
            "--root",
            str(root),
            "task",
            "add",
            "late",
            "--run-id",
            run_id,
            "--summary",
            "late task",
        ],
    )
    assert code == EXIT_INVALID_INPUT
    assert "TASK_GRAPH" in str(rejected["error"])

    _transition(capsys, root, run_id, Phase.REPLAN)
    code, rejected_in_replan = _call(
        capsys,
        [
            "--root",
            str(root),
            "task",
            "add",
            "late-without-flag",
            "--run-id",
            run_id,
            "--summary",
            "must be explicit",
        ],
    )
    assert code == EXIT_INVALID_INPUT
    assert "explicitly admitted" in str(rejected_in_replan["error"])

    code, late = _call(
        capsys,
        [
            "--root",
            str(root),
            "task",
            "add",
            "late",
            "--run-id",
            run_id,
            "--summary",
            "late task",
            "--acceptance",
            "covered",
            "--replan",
        ],
    )
    assert code == 0 and late["replan"] is True
    state = load_state(root / ".stackmarshal" / "runs" / run_id / "run.json", project_root=root)
    assert state.budget.used["architecture_replans"] == 1
    assert state.budget.used["scope_additions"] == 1
    graph = load_task_graph(root, required=True)
    assert [task["id"] for task in graph["tasks"]] == ["initial", "late"]
    _transition(capsys, root, run_id, Phase.IMPLEMENTATION)


def test_host_telemetry_sync_is_monotonic_and_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _start(root, capsys)
    _to_task_graph(capsys, root, run_id)
    _transition(capsys, root, run_id, Phase.IMPLEMENTATION)

    code, first = _call(
        capsys,
        [
            "--root",
            str(root),
            "activity",
            "sync-host",
            "--run-id",
            run_id,
            "--source",
            "devspace-session-a",
            "--tool-calls-total",
            "5",
        ],
    )
    assert code == 0 and first["delta"] == 5 and first["changed"] is True

    code, same = _call(
        capsys,
        [
            "--root",
            str(root),
            "activity",
            "sync-host",
            "--run-id",
            run_id,
            "--source",
            "devspace-session-a",
            "--tool-calls-total",
            "5",
        ],
    )
    assert code == 0 and same["delta"] == 0 and same["changed"] is False

    code, later = _call(
        capsys,
        [
            "--root",
            str(root),
            "activity",
            "sync-host",
            "--run-id",
            run_id,
            "--source",
            "devspace-session-a",
            "--tool-calls-total",
            "8",
        ],
    )
    assert code == 0 and later["delta"] == 3
    state = load_state(root / ".stackmarshal" / "runs" / run_id / "run.json", project_root=root)
    assert state.budget.used["tool_calls"] == 8
    assert state.progress["activity_by_phase"]["IMPLEMENTATION"]["tool-call"] == 8
    assert state.progress["host_telemetry"]["devspace-session-a"]["tool_calls_total"] == 8

    code, backwards = _call(
        capsys,
        [
            "--root",
            str(root),
            "activity",
            "sync-host",
            "--run-id",
            run_id,
            "--source",
            "devspace-session-a",
            "--tool-calls-total",
            "7",
        ],
    )
    assert code == EXIT_INVALID_INPUT
    assert "moved backwards" in str(backwards["error"])


def test_host_telemetry_budget_exhaustion_uses_formal_stop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run_id = _start(root, capsys)
    _to_task_graph(capsys, root, run_id)
    _transition(capsys, root, run_id, Phase.IMPLEMENTATION)

    state_path = root / ".stackmarshal" / "runs" / run_id / "run.json"
    state = load_state(state_path, project_root=root)
    limit = state.budget.limits["tool_calls"]

    code, stopped = _call(
        capsys,
        [
            "--root",
            str(root),
            "activity",
            "sync-host",
            "--run-id",
            run_id,
            "--source",
            "budget-probe",
            "--tool-calls-total",
            str(limit + 1),
        ],
    )

    assert code == EXIT_BUDGET
    assert stopped["status"] == Status.BUDGET_EXHAUSTED.value
    stopped_state = load_state(state_path, project_root=root)
    assert stopped_state.status is Status.BUDGET_EXHAUSTED
    assert "budget-probe" not in stopped_state.progress.get("host_telemetry", {})
