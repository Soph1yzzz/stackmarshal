from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from stackmarshal.cli import EXIT_COMPLETE, EXIT_INVALID_STATE, _safe_finalization_project, main
from stackmarshal.constants import Phase, Status
from stackmarshal.state import load_state
from stackmarshal.taskgraph import load_task_graph


def _call(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, object]]:
    code = main(argv)
    captured = capsys.readouterr()
    text = captured.out.strip() or captured.err.strip()
    return code, json.loads(text)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _move(root: Path, run_id: str, phase: Phase, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _call(
        capsys,
        ["--root", str(root), "state", "transition", phase.value, "--run-id", run_id],
    )
    assert code in {0, EXIT_COMPLETE}, payload


def test_finalization_project_rejects_workspace_escape_symlink(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside_state = tmp_path / "outside-state"
    outside_project = outside_state / "project"
    outside_project.mkdir(parents=True)
    (outside_project / "task-graph.json").write_text('{"schema_version":"1.0","tasks":[]}\n', encoding="utf-8")
    (outside_project / "task-graph.md").write_text("# Task Graph\n", encoding="utf-8")
    try:
        (root / ".stackmarshal").symlink_to(outside_state, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")

    with pytest.raises(ValueError, match=r"symlink|escapes workspace"):
        _safe_finalization_project(root, require_audit=False)


def test_nested_workspace_live_orchestration_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Permanent E2E contract derived from RepoHealth/v1.1.1 dogfooding.

    The requested child starts empty beneath an unrelated parent Git repository,
    bootstraps its own repository inside one authoritative run, records live
    task/budget activity, finalizes bookkeeping before terminal state, permits a
    Git-only housekeeping commit, and ends COMPLETE with a clean terminal seal and
    no orphan RUNNING run.
    """

    parent = tmp_path / "outer-repository"
    parent.mkdir()
    _git(parent, "init", "-q")
    _git(parent, "config", "user.email", "contract@example.invalid")
    _git(parent, "config", "user.name", "Live Contract")
    (parent / "outer.txt").write_text("outer\n", encoding="utf-8")
    _git(parent, "add", "outer.txt")
    _git(parent, "commit", "-qm", "outer baseline")

    child = parent / "lab" / "fresh-child"
    child.mkdir(parents=True)

    code, initialized = _call(capsys, ["--root", str(child), "init"])
    assert code == 0 and initialized["initialized"] is True
    code, started = _call(
        capsys,
        [
            "--root",
            str(child),
            "start",
            "--invocation",
            "$stackmarshal build permanent live orchestration contract",
        ],
    )
    assert code == 0
    run_id = str(started["run_id"])
    run_path = child / ".stackmarshal" / "runs" / run_id / "run.json"
    initial = load_state(run_path)
    assert initial.project.repository_owned is False
    assert initial.project.git_toplevel is None
    assert initial.project.git_head is None

    _move(child, run_id, Phase.INTENT_NORMALIZATION, capsys)
    _git(child, "init", "-q")
    _git(child, "config", "user.email", "contract@example.invalid")
    _git(child, "config", "user.name", "Live Contract")
    _move(child, run_id, Phase.ENVIRONMENT_AUDIT, capsys)

    for phase in (
        Phase.RESEARCH_GATE,
        Phase.CAPABILITY_MAPPING,
        Phase.ARCHITECTURE_FREEZE,
        Phase.TASK_GRAPH,
    ):
        _move(child, run_id, phase, capsys)

    for task_id, summary in (("implement", "Create deliverable"), ("verify", "Verify deliverable")):
        code, payload = _call(
            capsys,
            [
                "--root",
                str(child),
                "task",
                "add",
                task_id,
                "--run-id",
                run_id,
                "--summary",
                summary,
                "--acceptance",
                f"{task_id} evidence exists",
            ],
        )
        assert code == 0 and payload["added"] is True

    _move(child, run_id, Phase.IMPLEMENTATION, capsys)
    code, _ = _call(capsys, ["--root", str(child), "task", "start", "implement", "--run-id", run_id])
    assert code == 0
    code, _ = _call(
        capsys,
        [
            "--root",
            str(child),
            "activity",
            "record",
            "tool-call",
            "--run-id",
            run_id,
            "--amount",
            "4",
            "--detail",
            "bounded implementation batch",
        ],
    )
    assert code == 0
    (child / "deliverable.txt").write_text("live orchestration contract\n", encoding="utf-8")
    code, _ = _call(
        capsys,
        [
            "--root",
            str(child),
            "activity",
            "record",
            "implementation",
            "--run-id",
            run_id,
            "--detail",
            "deliverable created during IMPLEMENTATION",
        ],
    )
    assert code == 0
    code, _ = _call(
        capsys,
        [
            "--root",
            str(child),
            "task",
            "complete",
            "implement",
            "--run-id",
            run_id,
            "--evidence",
            "deliverable.txt exists",
        ],
    )
    assert code == 0

    _git(child, "add", ".")
    _git(child, "commit", "-qm", "contract deliverable")
    _move(child, run_id, Phase.VERIFICATION, capsys)

    code, _ = _call(capsys, ["--root", str(child), "task", "start", "verify", "--run-id", run_id])
    assert code == 0
    code, _ = _call(
        capsys,
        [
            "--root",
            str(child),
            "activity",
            "record",
            "tool-call",
            "--run-id",
            run_id,
            "--amount",
            "2",
            "--detail",
            "bounded verification batch",
        ],
    )
    assert code == 0
    assert (child / "deliverable.txt").read_text(encoding="utf-8") == "live orchestration contract\n"
    code, _ = _call(
        capsys,
        ["--root", str(child), "activity", "record", "verification", "--run-id", run_id],
    )
    assert code == 0
    code, _ = _call(
        capsys,
        [
            "--root",
            str(child),
            "task",
            "complete",
            "verify",
            "--run-id",
            run_id,
            "--evidence",
            "deliverable content verified",
        ],
    )
    assert code == 0

    # Finalization writes an atomic task-graph temporary file. A pre-existing
    # symlink there must fail closed instead of redirecting that write.
    outside_tmp = tmp_path / "outside-task-graph.json"
    outside_tmp.write_text("outside\n", encoding="utf-8")
    temporary_graph = child / ".stackmarshal" / "project" / "task-graph.json.tmp"
    try:
        temporary_graph.symlink_to(outside_tmp)
    except OSError:
        pass
    else:
        code, unsafe_finalize = _call(capsys, ["--root", str(child), "finalize", "--run-id", run_id])
        assert code == EXIT_INVALID_STATE
        assert any("temporary task graph" in str(error) for error in unsafe_finalize["errors"])
        assert outside_tmp.read_text(encoding="utf-8") == "outside\n"
        temporary_graph.unlink()

    deliverable = child / "deliverable.txt"
    deliverable.write_text("changed after verification\n", encoding="utf-8")
    code, rejected_finalize = _call(capsys, ["--root", str(child), "finalize", "--run-id", run_id])
    assert code == EXIT_INVALID_STATE
    assert "workspace_changed_after_verification" in rejected_finalize["errors"]
    deliverable.write_text("live orchestration contract\n", encoding="utf-8")

    code, finalized = _call(capsys, ["--root", str(child), "finalize", "--run-id", run_id])
    assert code == 0 and finalized["finalized"] is True

    late_evidence = child / ".stackmarshal" / "project" / "late-note.md"
    late_evidence.write_text("late evidence\n", encoding="utf-8")
    code, rejected_project = _call(
        capsys,
        ["--root", str(child), "state", "transition", "COMPLETE", "--run-id", run_id],
    )
    assert code == EXIT_INVALID_STATE
    assert "finalization_file_set_changed" in rejected_project["errors"]
    late_evidence.unlink()

    # Build/dist/release outputs are terminal deliverables even when ignored by Git.
    # Mutating one after finalization must invalidate COMPLETE.
    dist = child / "dist"
    dist.mkdir()
    tampered = dist / "artifact.bin"
    tampered.write_bytes(b"tampered-after-finalization")
    code, rejected = _call(
        capsys,
        ["--root", str(child), "state", "transition", "COMPLETE", "--run-id", run_id],
    )
    assert code == EXIT_INVALID_STATE
    assert "workspace_changed_after_finalization" in rejected["errors"]
    tampered.unlink()
    dist.rmdir()

    _git(child, "add", ".stackmarshal/project")
    _git(child, "commit", "-qm", "finalize stackmarshal bookkeeping")

    code, completed = _call(
        capsys,
        ["--root", str(child), "state", "transition", "COMPLETE", "--run-id", run_id],
    )
    assert code == EXIT_COMPLETE
    assert completed["status"] == "COMPLETE"

    runs = list((child / ".stackmarshal" / "runs").glob("*/run.json"))
    assert runs == [run_path]
    final = load_state(run_path)
    assert final.status is Status.COMPLETE
    assert final.project.repository_owned is True
    assert final.project.git_toplevel == str(child.resolve())
    assert final.project.repository_lineage
    assert final.budget.used["tool_calls"] == 6
    assert final.budget.used["attempts_per_task"] == 1
    assert final.progress["activity_by_phase"]["IMPLEMENTATION"]["tool-call"] == 4
    assert final.progress["activity_by_phase"]["VERIFICATION"]["tool-call"] == 2
    assert final.progress["completion_gate"]["validated"] is True
    assert final.progress["completion_gate"]["finalization"] == "sealed"
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=child, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert final.progress["terminal_seal"]["git_head"] == current_head
    assert final.progress["terminal_seal"]["git_dirty"] is False
    assert final.progress["terminal_seal"]["git_dirty_paths"] == []

    graph = load_task_graph(child, required=True)
    assert all(task["status"] == "done" and task["evidence"] for task in graph["tasks"])
    events = run_path.with_name("events.jsonl").read_text(encoding="utf-8")
    assert events.count("project_identity_migrated") == 2
    assert "workspace_repository_bootstrap" in events
    assert "repository_first_commit" in events
    assert "activity_recorded" in events
    assert "task_completed" in events
    assert "finalization_completed" in events
    assert not any(load_state(path).status is Status.RUNNING for path in runs)
