from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from stackmarshal.cli import EXIT_COMPLETE, main
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


def test_fresh_nested_workspace_live_run_experiment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reproduce the Phase 3B failure shape against the Nextpatch candidate.

    The requested child starts empty beneath an unrelated parent Git repository,
    bootstraps its own repository during the same StackMarshal run, performs live
    task/budget accounting, and must terminate with no orphan RUNNING state.
    """

    parent = tmp_path / "outer-repository"
    parent.mkdir()
    _git(parent, "init", "-q")
    _git(parent, "config", "user.email", "experiment@example.invalid")
    _git(parent, "config", "user.name", "Nextpatch Experiment")
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
            "$stackmarshal build nested Nextpatch experiment",
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

    # Bootstrap the child repository without abandoning/replacing the active run.
    _git(child, "init", "-q")
    _git(child, "config", "user.email", "experiment@example.invalid")
    _git(child, "config", "user.name", "Nextpatch Experiment")
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
    code, _ = _call(
        capsys,
        ["--root", str(child), "task", "start", "implement", "--run-id", run_id],
    )
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
    (child / "deliverable.txt").write_text("nextpatch experiment\n", encoding="utf-8")
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
            "deliverable created while IMPLEMENTATION is current",
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

    # First commit is a second, explicit lineage migration in the same run.
    _git(child, "add", ".")
    _git(child, "commit", "-qm", "experiment deliverable")
    _move(child, run_id, Phase.VERIFICATION, capsys)

    code, _ = _call(
        capsys,
        ["--root", str(child), "task", "start", "verify", "--run-id", run_id],
    )
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
    assert (child / "deliverable.txt").read_text(encoding="utf-8") == "nextpatch experiment\n"
    code, _ = _call(
        capsys,
        [
            "--root",
            str(child),
            "activity",
            "record",
            "verification",
            "--run-id",
            run_id,
            "--detail",
            "deliverable independently read during VERIFICATION",
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
            "verify",
            "--run-id",
            run_id,
            "--evidence",
            "deliverable content verified",
        ],
    )
    assert code == 0

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

    graph = load_task_graph(child, required=True)
    assert all(task["status"] == "done" and task["evidence"] for task in graph["tasks"])
    events = run_path.with_name("events.jsonl").read_text(encoding="utf-8")
    assert events.count("project_identity_migrated") == 2
    assert "workspace_repository_bootstrap" in events
    assert "repository_first_commit" in events
    assert "activity_recorded" in events
    assert "task_completed" in events
    assert not any(load_state(path).status is Status.RUNNING for path in runs)
