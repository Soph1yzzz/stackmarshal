from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from jsonschema import Draft202012Validator

from stackmarshal.cli import main
from stackmarshal.constants import Phase, Status
from stackmarshal.git_bootstrap import bootstrap_git, inspect_git
from stackmarshal.state import load_state, terminal_repository_snapshot
from stackmarshal.taskgraph import load_task_graph


def call(capsys: pytest.CaptureFixture[str], root: Path, *args: str) -> tuple[int, dict[str, object]]:
    code = main(["--root", str(root), *args])
    captured = capsys.readouterr()
    return code, json.loads(captured.out.strip() or captured.err.strip())


def start(capsys: pytest.CaptureFixture[str], root: Path, workflow: str = "build") -> str:
    code, _ = call(capsys, root, "init")
    assert code == 0
    code, data = call(capsys, root, "start", "--workflow", workflow, "--invocation", "$stackmarshal build")
    assert code == 0, data
    return str(data["run_id"])


def move(capsys: pytest.CaptureFixture[str], root: Path, run: str, phase: Phase) -> tuple[int, dict[str, object]]:
    return call(capsys, root, "state", "transition", phase.value, "--run-id", run)


def test_early_git_bootstrap_unicode_and_unborn(tmp_path: Path) -> None:
    root = tmp_path / "日本語 repo"
    root.mkdir()
    (root / "README.md").write_text("original content\n", encoding="utf-8")
    assert inspect_git(root)["status"] == "not_repository"
    result = bootstrap_git(root)
    assert result["initialized"] is True
    assert result["status"] == "unborn_repository"
    assert result["git_head"] is None
    assert (root / "README.md").read_text(encoding="utf-8") == "original content\n"
    assert bootstrap_git(root)["initialized"] is False
    assert subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True).stdout == b""


def test_nested_git_bootstrap_requires_explicit_opt_in(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    subprocess.run(["git", "init", str(parent)], check=True, capture_output=True)
    assert inspect_git(child)["status"] == "ancestor_repository_only"
    with pytest.raises(ValueError, match="nested Git bootstrap"):
        bootstrap_git(child)
    assert not (child / ".git").exists()
    assert bootstrap_git(child, allow_nested=True)["initialized"] is True


def test_git_bootstrap_ignores_inherited_git_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unrelated = tmp_path / "unrelated"
    requested = tmp_path / "requested"
    unrelated.mkdir()
    requested.mkdir()
    bootstrap_git(unrelated)
    monkeypatch.setenv("GIT_DIR", str(unrelated / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(unrelated))
    assert inspect_git(requested)["status"] == "not_repository"
    result = bootstrap_git(requested)
    assert result["initialized"] is True
    assert (requested / ".git").is_dir()
    assert inspect_git(unrelated)["status"] == "unborn_repository"


def test_host_write_mode_never_runs_shell_git_init(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "host-only"
    root.mkdir()
    code = main(["--root", str(root), "--write-mode", "host", "git", "bootstrap"])
    blocked = json.loads(capsys.readouterr().err.strip())
    assert code != 0 and "host-native Git" in blocked["error"]
    assert not (root / ".git").exists()


def test_terminal_git_status_preserves_japanese_path(tmp_path: Path) -> None:
    root = tmp_path / "日本語プロジェクト"
    root.mkdir()
    bootstrap_git(root)
    (root / "実機確認.txt").write_text("evidence\n", encoding="utf-8")
    snapshot = terminal_repository_snapshot(root)
    assert "実機確認.txt" in snapshot["git_dirty_paths"]


def test_checkpoint_distinguishes_no_git_from_unborn_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    no_git = tmp_path / "without-git"
    no_git.mkdir()
    run_a = start(capsys, no_git)
    assert call(capsys, no_git, "checkpoint", "create", "--run-id", run_a, "--next-action", "observe")[0] == 0
    checkpoint_a = no_git / ".stackmarshal" / "runs" / run_a / "checkpoint.md"
    assert "Git: `not_repository`" in checkpoint_a.read_text(encoding="utf-8")

    unborn = tmp_path / "unborn"
    unborn.mkdir()
    bootstrap_git(unborn)
    run_b = start(capsys, unborn)
    assert call(capsys, unborn, "checkpoint", "create", "--run-id", run_b, "--next-action", "observe")[0] == 0
    checkpoint_b = unborn / ".stackmarshal" / "runs" / run_b / "checkpoint.md"
    assert "Git: `unborn_repository`" in checkpoint_b.read_text(encoding="utf-8")


def test_quick_explore_skips_ceremony_but_not_evidence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run = start(capsys, root, "quick-explore")
    assert move(capsys, root, run, Phase.INTENT_NORMALIZATION)[0] == 0
    assert move(capsys, root, run, Phase.ENVIRONMENT_AUDIT)[0] == 0
    code, snapshot = call(capsys, root, "next", "--run-id", run)
    assert code == 0 and "IMPLEMENTATION" in snapshot["legal_transitions"]
    assert move(capsys, root, run, Phase.IMPLEMENTATION)[0] == 0
    code, added = call(capsys, root, "task", "add", "experiment", "--summary", "Probe", "--acceptance", "observed", "--run-id", run)
    assert code == 0 and added["added"] is True
    assert move(capsys, root, run, Phase.VERIFICATION)[0] == 0
    code, result = move(capsys, root, run, Phase.COMPLETE)
    assert code != 0 and "errors" in result
    assert any("mandatory_task_not_done" in str(error) for error in result["errors"])


def test_strict_build_does_not_skip_phases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run = start(capsys, root)
    assert move(capsys, root, run, Phase.INTENT_NORMALIZATION)[0] == 0
    assert move(capsys, root, run, Phase.ENVIRONMENT_AUDIT)[0] == 0
    assert move(capsys, root, run, Phase.IMPLEMENTATION)[0] != 0


def test_soft_exploration_exceed_requires_reason_and_hard_tool_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run = start(capsys, root, "quick-explore")
    for phase in (Phase.INTENT_NORMALIZATION, Phase.ENVIRONMENT_AUDIT, Phase.IMPLEMENTATION):
        assert move(capsys, root, run, phase)[0] == 0
    for _ in range(3):
        assert call(capsys, root, "activity", "record", "research-round", "--run-id", run)[0] == 0
    code, _ = call(capsys, root, "activity", "record", "research-round", "--run-id", run)
    assert code != 0
    code, record = call(capsys, root, "activity", "record", "research-round", "--run-id", run, "--reason", "new engine evidence")
    assert code == 0 and record["activity"]["soft_exceeded"] is True
    state = load_state(root / ".stackmarshal" / "runs" / run / "run.json", project_root=root)
    assert state.progress["soft_limit_overrides"][0]["reason"] == "new engine evidence"
    code, stopped = call(capsys, root, "activity", "record", "tool-call", "--amount", "121", "--run-id", run)
    assert code != 0 and stopped["status"] == Status.BUDGET_EXHAUSTED.value


def test_task_amend_replan_invalidates_old_evidence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run = start(capsys, root)
    for phase in (Phase.INTENT_NORMALIZATION, Phase.ENVIRONMENT_AUDIT, Phase.RESEARCH_GATE,
                  Phase.CAPABILITY_MAPPING, Phase.ARCHITECTURE_FREEZE, Phase.TASK_GRAPH):
        assert move(capsys, root, run, phase)[0] == 0
    assert call(capsys, root, "task", "add", "method", "--summary", "old approach", "--acceptance", "old test", "--run-id", run)[0] == 0
    assert move(capsys, root, run, Phase.IMPLEMENTATION)[0] == 0
    assert call(capsys, root, "task", "complete", "method", "--evidence", "old succeeded", "--run-id", run)[0] == 0
    code, _ = call(capsys, root, "task", "amend", "method", "--summary", "new approach", "--acceptance", "new test", "--reason", "new observation", "--run-id", run)
    assert code != 0
    assert move(capsys, root, run, Phase.REPLAN)[0] == 0
    code, result = call(capsys, root, "task", "amend", "method", "--summary", "new approach", "--acceptance", "new test", "--reason", "new observation", "--run-id", run)
    assert code == 0 and result["amended"] is True
    task = load_task_graph(root, required=True)["tasks"][0]
    assert task["status"] == "pending" and task["evidence"] == []
    assert task["amendments"][0]["previous_evidence"] == ["old succeeded"]
    assert task["amendments"][0]["previous_acceptance"] == ["old test"]
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "task-graph.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(
        json.loads((root / ".stackmarshal" / "project" / "task-graph.json").read_text(encoding="utf-8"))
    )


def test_evidence_reconcile_read_only_never_promotes_work(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run = start(capsys, root)
    code, checkpoint = call(capsys, root, "checkpoint", "create", "--run-id", run, "--next-action", "Resume later")
    assert code == 0 and checkpoint["succeeded"] is True
    state_path = root / ".stackmarshal" / "runs" / run / "run.json"
    old_bytes = state_path.read_bytes()
    (root / "実機確認.txt").write_text("external work\n", encoding="utf-8")
    code, report = call(capsys, root, "evidence", "reconcile", "--run-id", run)
    assert code == 0 and report["completion_claimable"] is False
    assert "checkpoint_worktree_changed" in report["differences"]
    assert report["external_work"] == "unverified"
    assert state_path.read_bytes() == old_bytes


def test_release_audit_requires_real_hash_bound_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run = start(capsys, root, "release-audit")
    for phase in (Phase.INTENT_NORMALIZATION, Phase.ENVIRONMENT_AUDIT, Phase.RESEARCH_GATE,
                  Phase.CAPABILITY_MAPPING, Phase.ARCHITECTURE_FREEZE, Phase.TASK_GRAPH,
                  Phase.IMPLEMENTATION, Phase.VERIFICATION):
        assert move(capsys, root, run, phase)[0] == 0
    code, snapshot = call(capsys, root, "next", "--run-id", run)
    assert code == 0 and "missing_release_audit_evidence" in snapshot["completion_prerequisites"]
    for filename in ("tests.txt", "security.txt", "artifacts.txt"):
        (root / filename).write_text("evidence\n", encoding="utf-8")
    code, _ = call(capsys, root, "release-evidence", "record", "--run-id", run,
                   "--tests", "../escape.txt", "--security", "security.txt", "--artifacts", "artifacts.txt")
    assert code != 0
    code, recorded = call(capsys, root, "release-evidence", "record", "--run-id", run,
                          "--tests", "tests.txt", "--security", "security.txt", "--artifacts", "artifacts.txt")
    assert code == 0 and recorded["recorded"] is True
    (root / "security.txt").write_text("tampered\n", encoding="utf-8")
    code, snapshot = call(capsys, root, "next", "--run-id", run)
    assert code == 0 and "release_evidence_changed:security" in snapshot["completion_prerequisites"]
