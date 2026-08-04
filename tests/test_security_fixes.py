from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from stackmarshal.acquisition import AcquisitionReceipt, rollback
from stackmarshal.checkpoint import create_checkpoint, inspect_checkpoint
from stackmarshal.cli import EXIT_INVALID_INPUT, main
from stackmarshal.config import default_config
from stackmarshal.constants import CommandClass, Mode, Status
from stackmarshal.security import classify_command
from stackmarshal.state import create_run, project_info


def test_command_classification_fails_closed_for_unknown_and_variants() -> None:
    cases = [
        (["curl", "--data", "x=1", "https://example.invalid"], CommandClass.NETWORK_WRITE),
        (["gh", "api", "repos/o/r", "--method", "POST"], CommandClass.NETWORK_WRITE),
        (["terraform", "apply", "-auto-approve"], CommandClass.BILLABLE_ACTION),
        (["docker", "push", "example/image"], CommandClass.PUBLICATION),
        (["custom-agent-tool", "--do-something"], CommandClass.READ_ONLY),
        (["python", "-c", "import os; os.remove('x')"], CommandClass.PROJECT_WRITE),
        (["git", "status", ";", "rm", "-rf", "."], CommandClass.PRIVILEGED),
    ]
    for argv, expected in cases:
        decision = classify_command(argv)
        assert decision.command_class is expected
        assert decision.approval_required is True
    assert classify_command(["git", "status"]).approval_required is False


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
        "forged", "file://forged", "1", None, None, str(root), (str(root),), (str(root),), "now"
    )
    with pytest.raises(ValueError, match="workspace root"):
        rollback(root_receipt, root)
    assert root.exists()

    unrelated_receipt = AcquisitionReceipt(
        "forged",
        "file://forged",
        "1",
        None,
        None,
        str(unrelated),
        (),
        (str(unrelated),),
        "now",
    )
    with pytest.raises(ValueError, match="not created"):
        rollback(unrelated_receipt, root)
    assert (unrelated / "keep.txt").exists()


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
