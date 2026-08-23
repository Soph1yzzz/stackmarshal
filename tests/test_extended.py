from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from stackmarshal.acquisition import (
    AcquisitionReceipt,
    install_project_file,
    rollback,
    save_receipt,
)
from stackmarshal.adapters.codex import CodexAdapter
from stackmarshal.budget import check, consume
from stackmarshal.checkpoint import create_checkpoint, inspect_checkpoint
from stackmarshal.config import default_config, load_config
from stackmarshal.constants import CommandClass, Mode, Phase, Status
from stackmarshal.integrity import sign_record
from stackmarshal.lock import verify_lock
from stackmarshal.models import BudgetState, ProgressSnapshot
from stackmarshal.progress import evaluate
from stackmarshal.research import EvidenceBundle, bounded_candidates, research_required
from stackmarshal.scoring import score_candidate
from stackmarshal.security import classify_command, inspect_package_manifest
from stackmarshal.state import append_event, create_run, load_state, save_state, stop, transition
from stackmarshal.validation import validate_json_file, validate_run_state


def test_config_profiles_and_toml_overrides(tmp_path: Path) -> None:
    assert default_config("deep").limits["tool_calls"] == 220
    with pytest.raises(ValueError, match="Unknown budget profile"):
        default_config("infinite")
    path = tmp_path / "stackmarshal.toml"
    path.write_text(
        """schema_version = "1.0"
budget_profile = "quick"
autonomy = "guarded"
language = "ja"
[limits]
tool_calls = 7
[approval]
publication = true
[state]
checkpoint_on_complete = true
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.budget_profile == "quick"
    assert config.limits["tool_calls"] == 7
    assert config.approval["publication"] is True
    assert config.state["checkpoint_on_complete"] is True
    assert load_config(tmp_path / "missing.toml").budget_profile == "standard"


def test_project_config_cannot_weaken_safety_limits_or_approvals(tmp_path: Path) -> None:
    path = tmp_path / "stackmarshal.toml"

    path.write_text('budget_profile = "deep"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="may not select the deep budget profile"):
        load_config(path)

    path.write_text('[limits]\ntool_calls = 121\n', encoding="utf-8")
    with pytest.raises(ValueError, match="may only tighten budget limits"):
        load_config(path)

    path.write_text('[approval]\npublication = false\n', encoding="utf-8")
    with pytest.raises(ValueError, match="may not disable required approval"):
        load_config(path)

    path.write_text('autonomy = "autonomous"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="may not weaken autonomy"):
        load_config(path)


def test_budget_unknown_and_check() -> None:
    budget = BudgetState("test", {"x": 2}, {})
    assert consume(budget, "x", 2).allowed
    assert check(budget)[0].allowed
    with pytest.raises(KeyError, match="Unknown budget"):
        consume(budget, "y")


def test_all_security_command_classes_and_manifest_findings() -> None:
    cases = [
        (["git", "status"], CommandClass.READ_ONLY, False),
        (["git", "commit", "-m", "x"], CommandClass.PROJECT_WRITE, False),
        (["npm", "install", "-g", "x"], CommandClass.GLOBAL_WRITE, True),
        (["curl", "-X", "POST", "https://example.invalid"], CommandClass.NETWORK_WRITE, True),
        (["cat", ".ssh/id_rsa"], CommandClass.SECRET_ACCESS, True),
        (["gh", "release", "create", "v1"], CommandClass.PUBLICATION, True),
        (["sudo", "apt", "install", "x"], CommandClass.PRIVILEGED, True),
        (["rm", "-rf", "build"], CommandClass.PROJECT_WRITE, True),
    ]
    for argv, expected, approval in cases:
        decision = classify_command(argv)
        assert decision.command_class is expected
        assert decision.approval_required is approval
    findings = inspect_package_manifest(
        """{"scripts":{"preinstall":"x","prepare":"x","install":"x"},
        "x":"powershell -Command IEX something"}"""
    )
    assert findings == [
        "install_hook:install",
        "install_hook:preinstall",
        "install_hook:prepare",
        "powershell_dynamic_execution",
    ]


def test_validation_rejects_all_malformed_shapes(tmp_path: Path) -> None:
    invalid = {
        "schema_version": "9.0",
        "mode": "wat",
        "phase": "wat",
        "status": "wat",
        "invocation": {"explicit": False},
        "budget": {"limits": {"x": 1}, "used": {"x": "bad", "y": -1}},
    }
    errors = validate_run_state(invalid)
    assert "unsupported_schema_version" in errors
    assert "invalid_mode" in errors
    assert "invalid_phase" in errors
    assert "invalid_status" in errors
    assert "invocation_not_explicit" in errors
    assert "invalid_budget_value:x" in errors
    assert "negative_budget:y" in errors

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    assert validate_json_file(array, "run-state")["errors"] == ["expected_json_object"]
    candidate = tmp_path / "candidate.json"
    candidate.write_text("{}", encoding="utf-8")
    assert not validate_json_file(candidate, "candidate")["valid"]
    assert not validate_json_file(candidate, "capability-map")["valid"]
    assert not validate_json_file(candidate, "checkpoint")["valid"]
    assert validate_json_file(candidate, "unknown")["errors"] == ["unknown_kind:unknown"]


def test_progress_all_observable_dimensions() -> None:
    previous = ProgressSnapshot(
        acceptance_passed=1,
        tests_passed=1,
        incomplete_tasks=5,
        blockers=4,
        uncertainty=3,
        root_causes=0,
        safe_alternatives=0,
    )
    current = ProgressSnapshot(
        acceptance_passed=2,
        tests_passed=2,
        incomplete_tasks=4,
        blockers=3,
        uncertainty=2,
        root_causes=1,
        safe_alternatives=1,
    )
    result = evaluate(previous, current)
    assert set(result["improved_fields"]) == {
        "acceptance_passed",
        "tests_passed",
        "incomplete_tasks",
        "blockers",
        "uncertainty",
        "root_causes",
        "safe_alternatives",
    }


def test_research_bundle_and_scoring_errors() -> None:
    bundle = EvidenceBundle(selected_patterns=["bounded"], sources=[{"url": "x"}])
    assert bundle.to_dict()["selected_patterns"] == ["bounded"]
    assert bounded_candidates([{"id": 1}], 0) == []
    with pytest.raises(ValueError, match="negative"):
        bounded_candidates([], -1)
    assert not research_required(trivial_edit=True, new_app=True)
    assert not research_required(fixed_technology=True, new_dependency=True)
    assert not research_required()
    with pytest.raises(ValueError, match="between 0 and 1"):
        score_candidate({"scores": {"requirement_fit": 2}, "risks": []})


def test_lock_malformed_entries_and_workspace_escape(tmp_path: Path) -> None:
    path = tmp_path / "lock.json"
    path.write_text(json.dumps({"schema_version": "0", "entries": "bad"}), encoding="utf-8")
    result = verify_lock(path, tmp_path)
    assert result["errors"] == ["entries_must_be_array"]

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "entries": [
                    "bad",
                    {
                        "kind": "library",
                        "id": "x",
                        "source": "",
                        "version": None,
                        "commit": None,
                        "sha256": "0" * 64,
                        "license": "MIT",
                        "permissions": [],
                        "verification": [],
                        "selected_reason": "x",
                        "artifact": "../outside.txt",
                    },
                    {
                        "kind": "library",
                        "id": "y",
                        "source": "https://example.invalid",
                        "version": "1",
                        "commit": None,
                        "sha256": "0" * 64,
                        "license": "MIT",
                        "permissions": [],
                        "verification": [],
                        "selected_reason": "x",
                        "artifact": "missing.txt",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = verify_lock(path, tmp_path)["errors"]
    assert any("unpinned" in item for item in errors)
    assert any("workspace_escape" in item for item in errors)
    assert any("artifact_missing" in item for item in errors)


def test_acquisition_receipt_save_overwrite_and_directory_rollback(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("x", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    receipt = install_project_file(
        candidate_id="x",
        source_file=source,
        target_root=root,
        relative_target=Path("nested/x.txt"),
        source="https://example.invalid",
        version="1",
        commit=None,
    )
    receipt_path = root / "receipt.json"
    save_receipt(receipt, receipt_path)
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["candidate_id"] == "x"
    with pytest.raises(FileExistsError):
        install_project_file(
            candidate_id="x",
            source_file=source,
            target_root=root,
            relative_target=Path("nested/x.txt"),
            source="https://example.invalid",
            version="1",
            commit=None,
        )
    directory = root / "remove-me"
    directory.mkdir()
    dir_receipt = AcquisitionReceipt(
        **sign_record(
            {
                "candidate_id": "d",
                "source": "file://x",
                "version": "1",
                "commit": None,
                "sha256": None,
                "target": str(directory),
                "files_created": (str(directory),),
                "rollback": (str(directory),),
                "timestamp": "now",
            }
        )
    )
    with pytest.raises(ValueError, match="recursive directory"):
        rollback(dir_receipt, root)
    assert directory.exists()
    rollback(receipt, root)


def test_codex_adapter_capabilities_and_delegation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex_home = tmp_path / "codex-home"
    skill = codex_home / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Demo", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    adapter = CodexAdapter(tmp_path)
    environment = adapter.detect_environment()
    assert environment["workspace"] == str(tmp_path.resolve())
    capabilities = adapter.list_native_capabilities()
    assert any(item["id"] == "demo" for item in capabilities)
    assert adapter.execute_task({"id": "t1"})["status"] == "delegated_to_host"
    assert adapter.verify(tmp_path)["exists"] is True
    audit = tmp_path / "audit" / "environment.json"
    adapter.write_audit(audit)
    assert json.loads(audit.read_text(encoding="utf-8"))["native_capabilities"]


def test_events_stop_state_schema_and_checkpoint_warnings(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    seed = tmp_path / "seed.txt"
    seed.write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)

    state = create_run(tmp_path, "Use StackMarshal", Mode.BUILD, default_config())
    events = tmp_path / "events.jsonl"
    first = append_event(events, "one", state.phase, {"x": 1})
    second = append_event(events, "two", state.phase, {"x": 2})
    assert (first["seq"], second["seq"]) == (1, 2)
    transition(state, Phase.INTENT_NORMALIZATION)
    stop(state, Status.BLOCKED_EXTERNAL, "offline", {"service": "registry"})
    assert state.phase is Phase.CHECKPOINTING
    assert state.stop_reason and state.stop_reason["details"]["service"] == "registry"
    with pytest.raises(ValueError):
        stop(state, Status.COMPLETE, "invalid")

    state_path = tmp_path / "run.json"
    save_state(state, state_path)
    assert load_state(state_path).status is Status.BLOCKED_EXTERNAL
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    raw["schema_version"] = "2.0"
    state_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported schema"):
        load_state(state_path)

    # Create a clean checkpoint outside the repository, then change both HEAD and dirty state.
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "test state"], cwd=tmp_path, check=True)
    clean_state = create_run(tmp_path, "Use StackMarshal", Mode.BUILD, default_config())
    clean_state.status = Status.COMPLETE
    checkpoint_dir = tmp_path.parent / f"{tmp_path.name}-checkpoint"
    checkpoint, _ = create_checkpoint(clean_state, checkpoint_dir, next_action="none")
    other = tmp_path / "other.txt"
    other.write_text("other", encoding="utf-8")
    subprocess.run(["git", "add", "other.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "other"], cwd=tmp_path, check=True)
    with pytest.raises(ValueError, match="Git HEAD mismatch"):
        inspect_checkpoint(checkpoint, tmp_path)
    (tmp_path / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(ValueError, match=r"worktree fingerprint|Git HEAD mismatch"):
        inspect_checkpoint(checkpoint, tmp_path)
