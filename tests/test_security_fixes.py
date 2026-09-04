from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from stackmarshal.acquisition import AcquisitionReceipt, install_project_file, rollback
from stackmarshal.checkpoint import create_checkpoint, inspect_checkpoint
from stackmarshal.cli import EXIT_INVALID_INPUT, _finalization_files, main
from stackmarshal.config import default_config
from stackmarshal.constants import CommandClass, Mode, Status
from stackmarshal.integrity import sign_record, signing_key_path
from stackmarshal.security import classify_command
from stackmarshal.taskgraph import add_task, load_task_graph
from stackmarshal.validation import validate_json_file
from stackmarshal.state import (
    _validate_fingerprint_path,
    _windows_reserved_component,
    create_run,
    load_state,
    project_info,
    save_state,
    terminal_workspace_fingerprint,
    workspace_fingerprint,
)


def test_windows_reserved_device_name_detection_is_component_aware() -> None:
    assert _windows_reserved_component(Path("NUL")) == "NUL"
    assert _windows_reserved_component(Path("nested") / "nul.txt") == "nul.txt"
    assert _windows_reserved_component(Path("COM1.")) == "COM1."
    assert _windows_reserved_component(Path("safe") / "null.txt") is None
    assert _windows_reserved_component(Path("safe") / "COM10.txt") is None
    with pytest.raises(ValueError, match=r"Windows reserved device name.*nested/NUL\.txt"):
        _validate_fingerprint_path(Path("nested") / "NUL.txt", platform_name="nt")
    _validate_fingerprint_path(Path("nested") / "NUL.txt", platform_name="posix")


def test_command_classification_fails_closed_for_unknown_and_variants() -> None:
    cases = [
        (["curl", "--data", "x=1", "https://example.invalid"], CommandClass.NETWORK_WRITE),
        (["gh", "api", "repos/o/r", "--method", "POST"], CommandClass.NETWORK_WRITE),
        (["terraform", "apply", "-auto-approve"], CommandClass.BILLABLE_ACTION),
        (["docker", "push", "example/image"], CommandClass.PUBLICATION),
        (["custom-agent-tool", "--do-something"], CommandClass.READ_ONLY),
        (["cat", ".env.production"], CommandClass.SECRET_ACCESS),
        (["find", ".", "-delete"], CommandClass.PROJECT_WRITE),
        (["python", "-c", "import os; os.remove('x')"], CommandClass.PROJECT_WRITE),
        (["git", "status", ";", "rm", "-rf", "."], CommandClass.PRIVILEGED),
        (["git", "grep", "--open-files-in-pager=echo", "needle"], CommandClass.PROJECT_WRITE),
        (["git", "diff", "--ext-diff"], CommandClass.PROJECT_WRITE),
        (["git", "diff", "--textconv"], CommandClass.PROJECT_WRITE),
        (["git", "diff", "--output=outside.patch"], CommandClass.PROJECT_WRITE),
        (["git", "diff", "--no-index", "one", "two"], CommandClass.PROJECT_WRITE),
        (["git", "-c", "alias.escape=!echo", "escape"], CommandClass.PROJECT_WRITE),
        (["git", "local-alias-that-might-execute"], CommandClass.PROJECT_WRITE),
    ]
    for argv, expected in cases:
        decision = classify_command(argv)
        assert decision.command_class is expected
        assert decision.approval_required is True
    assert classify_command(["git", "status"]).approval_required is False


def test_init_rejects_symlinked_state_and_gitignore_targets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for target_name in (".stackmarshal", ".gitignore"):
        root = tmp_path / target_name.replace(".", "")
        root.mkdir()
        outside = tmp_path / f"outside-{root.name}"
        if target_name == ".stackmarshal":
            outside.mkdir()
        else:
            outside.write_text("sentinel\n", encoding="utf-8")
        link = root / target_name
        try:
            link.symlink_to(outside, target_is_directory=outside.is_dir())
        except OSError as exc:
            pytest.skip(f"Symlink creation is unavailable: {exc}")

        code = main(["--root", str(root), "init"])
        assert code == EXIT_INVALID_INPUT
        assert "symlink" in capsys.readouterr().err.casefold()
        if outside.is_file():
            assert outside.read_text(encoding="utf-8") == "sentinel\n"
        else:
            assert list(outside.iterdir()) == []


def test_init_rejects_windows_junction_state_escape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    root = tmp_path / "junction-project"
    root.mkdir()
    outside = tmp_path / "junction-outside"
    outside.mkdir()
    junction = root / ".stackmarshal"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"Junction creation is unavailable: {created.stderr or created.stdout}")
    try:
        code = main(["--root", str(root), "init"])
        assert code == EXIT_INVALID_INPUT
        assert "escapes the workspace" in capsys.readouterr().err
        assert list(outside.iterdir()) == []
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(junction)], check=False, capture_output=True)


def test_finalization_evidence_rejects_nested_windows_junction(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    root = tmp_path / "finalization-project"
    project = root / ".stackmarshal" / "project"
    project.mkdir(parents=True)
    for name in ("task-graph.json", "task-graph.md", "environment-audit.json"):
        (project / name).write_text("{}\n" if name.endswith(".json") else "# evidence\n", encoding="utf-8")
    outside = tmp_path / "finalization-outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("must-not-be-sealed\n", encoding="utf-8")
    junction = project / "linked-evidence"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"Junction creation is unavailable: {created.stderr or created.stdout}")
    try:
        with pytest.raises(ValueError, match="escapes project state"):
            _finalization_files(root)
        assert secret.read_text(encoding="utf-8") == "must-not-be-sealed\n"
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(junction)], check=False, capture_output=True)


def test_workspace_fingerprints_reject_windows_junction_reads(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    root = tmp_path / "fingerprint-project"
    root.mkdir()
    outside = tmp_path / "fingerprint-outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("must-not-be-read\n", encoding="utf-8")
    junction = root / "payload-link"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"Junction creation is unavailable: {created.stderr or created.stdout}")
    try:
        with pytest.raises(ValueError, match="escapes during fingerprint"):
            workspace_fingerprint(root)
        with pytest.raises(ValueError, match="escapes during fingerprint"):
            terminal_workspace_fingerprint(root)
        assert secret.read_text(encoding="utf-8") == "must-not-be-read\n"
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(junction)], check=False, capture_output=True)


def test_run_id_path_traversal_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside" / "run.json"
    outside.parent.mkdir()
    outside.write_text('{"sentinel": true}', encoding="utf-8")
    code = main(
        [
            "--root",
            str(root),
            "state",
            "show",
            "--run-id",
            "../../outside",
        ]
    )
    assert code == EXIT_INVALID_INPUT
    assert "Invalid StackMarshal run id" in capsys.readouterr().err
    assert json.loads(outside.read_text(encoding="utf-8")) == {"sentinel": True}


def test_forged_rollback_cannot_delete_workspace_root_or_unrelated_directory(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    unrelated = root / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep", encoding="utf-8")

    root_receipt = AcquisitionReceipt(
        **sign_record(
            {
                "candidate_id": "forged",
                "source": "file://forged",
                "version": "1",
                "commit": None,
                "sha256": None,
                "target": str(root),
                "files_created": (str(root),),
                "rollback": (str(root),),
                "timestamp": "now",
            }
        )
    )
    with pytest.raises(ValueError, match="workspace root"):
        rollback(root_receipt, root)
    assert root.exists()

    unrelated_receipt = AcquisitionReceipt(
        **sign_record(
            {
                "candidate_id": "forged",
                "source": "file://forged",
                "version": "1",
                "commit": None,
                "sha256": None,
                "target": str(unrelated),
                "files_created": (),
                "rollback": (str(unrelated),),
                "timestamp": "now",
            }
        )
    )
    with pytest.raises(ValueError, match="exact installed target"):
        rollback(unrelated_receipt, root)
    assert (unrelated / "keep.txt").exists()


def test_receipt_tampering_and_replaced_files_block_rollback(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("installed", encoding="utf-8")
    receipt = install_project_file(
        candidate_id="safe",
        source_file=source,
        target_root=root,
        relative_target=Path("installed.txt"),
        source="file://source",
        version="1",
        commit=None,
    )
    unrelated = root / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    forged = replace(
        receipt,
        target=str(unrelated),
        files_created=(str(unrelated),),
        rollback=(str(unrelated),),
    )
    with pytest.raises(ValueError, match="signature mismatch"):
        rollback(forged, root)
    assert unrelated.exists()

    installed = root / "installed.txt"
    installed.write_text("replaced", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after installation"):
        rollback(receipt, root)
    assert installed.exists()


def test_live_run_state_tampering_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    state = create_run(root, "Use StackMarshal to build", Mode.BUILD, default_config())
    state_path = root / ".stackmarshal" / "runs" / state.run_id / "run.json"
    save_state(state, state_path)
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["integrity_algorithm"] == "hmac-sha256-v1"
    data["phase"] = "VERIFICATION"
    data["progress"] = {"live_contract_version": 1, "verified_workspace": {"workspace_fingerprint": "0" * 64}}
    state_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="signature mismatch"):
        load_state(state_path, project_root=root)


def test_unsigned_repository_live_state_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    state = create_run(root, "Use StackMarshal to build", Mode.BUILD, default_config())
    state_path = root / ".stackmarshal" / "runs" / state.run_id / "run.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(state.to_dict()), encoding="utf-8")
    assert validate_json_file(state_path, "run-state")["valid"] is False
    with pytest.raises(ValueError, match=r"Legacy unsigned StackMarshal run state.*stackmarshal migrate"):
        load_state(state_path, project_root=root)


def test_task_graph_tampering_and_unsigned_graph_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    add_task(root, "security", "verify live authority", acceptance=["signed state"])
    graph_path = root / ".stackmarshal" / "project" / "task-graph.json"
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    assert data["integrity_algorithm"] == "hmac-sha256-v1"
    data["tasks"][0]["status"] = "done"
    data["tasks"][0]["evidence"] = ["forged"]
    graph_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="signature mismatch"):
        load_task_graph(root, required=True)

    graph_path.write_text(json.dumps({"schema_version": "1.0", "tasks": []}), encoding="utf-8")
    assert validate_json_file(graph_path, "task-graph")["valid"] is False
    with pytest.raises(ValueError, match=r"Legacy unsigned StackMarshal task graph.*stackmarshal migrate"):
        load_task_graph(root, required=True)


def test_signing_key_inside_project_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("STACKMARSHAL_STATE_HOME", str(project / ".local-state"))
    state = create_run(project, "Use StackMarshal", Mode.BUILD, default_config())
    state.status = Status.CHECKPOINT_READY
    assert project.resolve() in signing_key_path().resolve(strict=False).parents
    with pytest.raises(ValueError, match="outside the project"):
        save_state(state, project / ".stackmarshal" / "runs" / state.run_id / "run.json")
    with pytest.raises(ValueError, match="outside the project"):
        add_task(project, "unsafe-key", "must reject repository-local signing key")
    with pytest.raises(ValueError, match="outside the project"):
        create_checkpoint(state, project / "checkpoint", next_action="stop")


def test_dirty_worktree_content_change_invalidates_checkpoint(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    dirty = tmp_path / "dirty.txt"
    dirty.write_text("version-one", encoding="utf-8")
    state = create_run(tmp_path, "Use StackMarshal", Mode.BUILD, default_config())
    state.status = Status.CHECKPOINT_READY
    checkpoint, _ = create_checkpoint(
        state, tmp_path.parent / f"{tmp_path.name}-checkpoint", next_action="continue"
    )
    dirty.write_text("version-two", encoding="utf-8")
    with pytest.raises(ValueError, match="worktree fingerprint"):
        inspect_checkpoint(checkpoint, tmp_path)


def test_checkpoint_cannot_be_forged_by_recomputing_plain_hash(tmp_path: Path) -> None:
    state = create_run(tmp_path, "Use StackMarshal", Mode.BUILD, default_config())
    state.status = Status.CHECKPOINT_READY
    checkpoint, _ = create_checkpoint(state, tmp_path / "run", next_action="safe action")
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    data["next_action"] = "attacker action"
    canonical = json.dumps(
        {key: value for key, value in data.items() if key != "integrity_hmac_sha256"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    # A plain digest is computable by an attacker, but it is not a valid HMAC signature.
    data["integrity_hmac_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    checkpoint.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="signature mismatch"):
        inspect_checkpoint(checkpoint, tmp_path)


def test_project_identity_binds_repository_lineage(tmp_path: Path) -> None:
    def initialize(message: str) -> None:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
        (tmp_path / "identity.txt").write_text(message, encoding="utf-8")
        subprocess.run(["git", "add", "identity.txt"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=tmp_path, check=True)

    initialize("first")
    first = project_info(tmp_path).identity_hash
    subprocess.run(["git", "checkout", "--orphan", "replacement"], cwd=tmp_path, check=True)
    subprocess.run(["git", "rm", "-rf", "."], cwd=tmp_path, check=True)
    (tmp_path / "identity.txt").write_text("replacement", encoding="utf-8")
    subprocess.run(["git", "add", "identity.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "replacement"], cwd=tmp_path, check=True)
    second = project_info(tmp_path).identity_hash
    assert first != second


def test_release_builder_rejects_symlink_inputs(tmp_path: Path) -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"
    spec = importlib.util.spec_from_file_location("stackmarshal_release_security", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = source / "leak.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")
    with pytest.raises(ValueError, match="symlink"):
        module.zip_tree(source, tmp_path / "unsafe.zip", "stackmarshal", 1_700_000_000)
