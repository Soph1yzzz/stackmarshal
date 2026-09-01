from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from stackmarshal.cli import (
    EXIT_BUDGET,
    EXIT_COMPLETE,
    EXIT_INVALID_STATE,
    _launcher_metadata_versions,
    _launcher_package_version,
    _path_stackmarshal_candidates,
    _read_managed_install_state,
    main,
)
from stackmarshal.constants import Phase, __version__
from stackmarshal.state import load_state, project_info, terminal_repository_snapshot
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


def test_managed_install_state_reports_missing_invalid_and_valid_files(tmp_path: Path) -> None:
    root = tmp_path / "managed"
    root.mkdir()
    assert _read_managed_install_state(root) == (None, None)

    state_path = root / "install-state.json"
    state_path.write_text("[]", encoding="utf-8")
    assert _read_managed_install_state(root) == (None, "managed_install_state_invalid")

    state_path.write_text("{not-json", encoding="utf-8")
    data, error = _read_managed_install_state(root)
    assert data is None
    assert error == "managed_install_state_unreadable:JSONDecodeError"

    state_path.write_text('{"version":"9.8.7"}', encoding="utf-8")
    assert _read_managed_install_state(root) == ({"version": "9.8.7"}, None)


def test_launcher_version_evidence_is_non_executing_and_bounded(tmp_path: Path) -> None:
    launcher = tmp_path / ("stackmarshal.cmd" if os.name == "nt" else "stackmarshal")
    launcher.write_text(
        'exec "C:/managed/versions/v9.8.7/venv/Scripts/python.exe" -m stackmarshal.cli\n',
        encoding="utf-8",
    )
    assert _launcher_package_version(launcher) == "9.8.7"

    unrelated = tmp_path / ("other.cmd" if os.name == "nt" else "other")
    unrelated.write_text("no version path here\n", encoding="utf-8")
    assert _launcher_package_version(unrelated) is None


def test_launcher_metadata_versions_are_reported_as_metadata_not_runtime_identity(tmp_path: Path) -> None:
    python_root = tmp_path / "Python311"
    scripts = python_root / "Scripts"
    site_packages = python_root / "Lib" / "site-packages"
    scripts.mkdir(parents=True)
    site_packages.mkdir(parents=True)
    launcher = scripts / "stackmarshal.exe"
    launcher.write_bytes(b"placeholder")
    metadata = site_packages / "stackmarshal-9.8.7.dist-info" / "METADATA"
    metadata.parent.mkdir()
    metadata.write_text("Metadata-Version: 2.1\nName: stackmarshal\nVersion: 9.8.7\n", encoding="utf-8")

    assert _launcher_package_version(launcher) is None
    assert _launcher_metadata_versions(launcher) == ["9.8.7"]


def test_path_candidate_inventory_does_not_execute_launchers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launcher_name = "stackmarshal.cmd" if os.name == "nt" else "stackmarshal"
    launcher = bin_dir / launcher_name
    launcher.write_text(
        'exec "C:/managed/versions/v9.8.7/venv/Scripts/python.exe" -m stackmarshal.cli\n',
        encoding="utf-8",
    )
    if os.name != "nt":
        launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    candidates = _path_stackmarshal_candidates()

    assert len(candidates) == 1
    assert Path(str(candidates[0]["path"])).name.casefold() == launcher_name.casefold()
    assert candidates[0]["version"] == "9.8.7"
    assert candidates[0]["metadata_versions"] == []


def _isolate_doctor_install_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "managed-base"
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(base))
        root = base / "StackMarshal"
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(base))
        root = base / "stackmarshal"
    monkeypatch.setenv("PATH", "")
    return root


def test_doctor_detects_stale_host_skill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex"
    skill = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f'---\nmetadata:\n  version: "{__version__}"\n---\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    _isolate_doctor_install_root(tmp_path, monkeypatch)

    code, payload = _call(capsys, ["doctor", "--host-skill-version", __version__])
    assert code == 0 and payload["ready"] is True
    assert payload["version_skew"] is False
    code, payload = _call(capsys, ["doctor", "--host-skill-version", "0.0.0"])
    assert code == EXIT_INVALID_STATE
    assert payload["restart_required"] is True


def test_doctor_detects_managed_cli_version_skew(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex"
    skill = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f'---\nmetadata:\n  version: "{__version__}"\n---\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    install_root = _isolate_doctor_install_root(tmp_path, monkeypatch)
    install_root.mkdir(parents=True)
    launcher = install_root / "bin" / ("stackmarshal.cmd" if os.name == "nt" else "stackmarshal")
    launcher.parent.mkdir()
    launcher.write_text("managed launcher placeholder\n", encoding="utf-8")
    (install_root / "install-state.json").write_text(
        json.dumps(
            {
                "version": "1.1.1",
                "cli": {"version": "1.1.1", "launcher": str(launcher)},
                "skill": {"version": "1.1.1"},
            }
        ),
        encoding="utf-8",
    )

    code, payload = _call(capsys, ["doctor", "--host-skill-version", __version__])
    assert code == EXIT_INVALID_STATE
    assert payload["ready"] is False
    assert payload["repair_required"] is True
    assert payload["version_skew"] is True
    assert payload["managed_install"]["version"] == "1.1.1"
    assert "stackmarshal_version_skew" in payload["warnings"]


def test_doctor_reports_resolved_managed_launcher_without_executing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex"
    skill = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f'---\nmetadata:\n  version: "{__version__}"\n---\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    install_root = _isolate_doctor_install_root(tmp_path, monkeypatch)
    launcher_name = "stackmarshal.cmd" if os.name == "nt" else "stackmarshal"
    launcher = install_root / "bin" / launcher_name
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        f'exec "C:/managed/versions/v{__version__}/venv/Scripts/python.exe" -m stackmarshal.cli\n',
        encoding="utf-8",
    )
    if os.name != "nt":
        launcher.chmod(0o755)
    (install_root / "install-state.json").write_text(
        json.dumps(
            {
                "version": __version__,
                "cli": {"version": __version__, "launcher": str(launcher)},
                "skill": {"version": __version__},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(launcher.parent))

    code, payload = _call(capsys, ["doctor", "--host-skill-version", __version__])

    assert code == 0
    assert payload["ready"] is True
    assert payload["version_skew"] is False
    assert payload["path_resolution"]["resolved_launcher_version"] == __version__
    assert len(payload["path_resolution"]["candidates"]) == 1
    assert payload["warnings"] == []


def test_doctor_fails_closed_on_malformed_managed_install_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex"
    skill = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f'---\nmetadata:\n  version: "{__version__}"\n---\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    install_root = _isolate_doctor_install_root(tmp_path, monkeypatch)
    install_root.mkdir(parents=True)
    (install_root / "install-state.json").write_text("{broken", encoding="utf-8")

    code, payload = _call(capsys, ["doctor", "--host-skill-version", __version__])

    assert code == EXIT_INVALID_STATE
    assert payload["repair_required"] is True
    assert payload["managed_install"]["state_error"] == "managed_install_state_unreadable:JSONDecodeError"
    assert "managed_install_state_unreadable:JSONDecodeError" in payload["warnings"]


def test_terminal_repository_snapshot_preserves_porcelain_status_columns(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "stackmarshal@example.invalid")
    _git(root, "config", "user.name", "StackMarshal Test")
    agents = root / "AGENTS.md"
    agents.write_text("initial\n", encoding="utf-8")
    _git(root, "add", "AGENTS.md")
    _git(root, "commit", "-m", "initial")
    agents.write_text("changed\n", encoding="utf-8")

    snapshot = terminal_repository_snapshot(root)

    assert snapshot["git_dirty"] is True
    assert snapshot["git_status_porcelain"] == [" M AGENTS.md"]
    assert snapshot["git_dirty_paths"] == ["AGENTS.md"]
