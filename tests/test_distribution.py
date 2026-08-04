from __future__ import annotations

import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile

from jsonschema import Draft202012Validator

from stackmarshal.checkpoint import create_checkpoint
from stackmarshal.config import default_config
from stackmarshal.constants import Mode, Status
from stackmarshal.state import create_run

ROOT = Path(__file__).resolve().parents[1]


def _load_release_module() -> object:
    path = ROOT / "scripts" / "build_release.py"
    spec = importlib.util.spec_from_file_location("stackmarshal_build_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_sdist_normalization_is_reproducible(tmp_path: Path) -> None:
    module = _load_release_module()
    archives = [tmp_path / "one.tar.gz", tmp_path / "two.tar.gz"]
    for index, path in enumerate(archives, start=1):
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
            info = tarfile.TarInfo("package/file.txt")
            payload = b"same-content"
            info.size = len(payload)
            info.mtime = index
            info.uid = index
            archive.addfile(info, io.BytesIO(payload))
        with path.open("wb") as raw, gzip.GzipFile(
            filename=f"source-{index}", mode="wb", fileobj=raw, mtime=index
        ) as compressed:
            compressed.write(tar_buffer.getvalue())
        module.normalize_tar_gz(path, 1_700_000_000)  # type: ignore[attr-defined]
    assert archives[0].read_bytes() == archives[1].read_bytes()


def test_release_metadata_uses_lf_line_endings(tmp_path: Path) -> None:
    module = _load_release_module()
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"payload")
    metadata = tmp_path / "metadata.json"
    checksums = tmp_path / "SHA256SUMS"

    module.write_json(metadata, {"value": 1})  # type: ignore[attr-defined]
    module.write_checksums(checksums, [artifact])  # type: ignore[attr-defined]

    assert b"\r\n" not in metadata.read_bytes()
    assert b"\r\n" not in checksums.read_bytes()
    assert checksums.read_bytes().endswith(b"  artifact.bin\n")


def test_release_zip_excludes_python_cache(tmp_path: Path) -> None:
    source = tmp_path / "skill"
    (source / "scripts" / "__pycache__").mkdir(parents=True)
    (source / "SKILL.md").write_text("# Skill", encoding="utf-8")
    (source / "scripts" / "tool.py").write_text("print('ok')", encoding="utf-8")
    (source / "scripts" / "tool.pyc").write_bytes(b"cache")
    (source / "scripts" / "__pycache__" / "tool.cpython-311.pyc").write_bytes(b"cache")
    destination = tmp_path / "skill.zip"
    module = _load_release_module()
    module.zip_tree(source, destination, "stackmarshal", 1_700_000_000)  # type: ignore[attr-defined]
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
    assert "stackmarshal/SKILL.md" in names
    assert "stackmarshal/scripts/tool.py" in names
    assert not any("__pycache__" in name or name.endswith((".pyc", ".pyo")) for name in names)


def test_json_schemas_are_valid_and_accept_runtime_examples(tmp_path: Path) -> None:
    schemas = {}
    for path in sorted((ROOT / "schemas").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schemas[path.stem] = schema

    state = create_run(tmp_path, "Use StackMarshal to build", Mode.BUILD, default_config())
    Draft202012Validator(schemas["run-state.schema"]).validate(state.to_dict())
    Draft202012Validator(schemas["candidate.schema"]).validate(
        {
            "id": "candidate-1",
            "kind": "library",
            "source": {"url": "https://example.invalid"},
            "scores": {},
            "risks": [],
            "decision": "pending",
        }
    )
    Draft202012Validator(schemas["capability-map.schema"]).validate(
        {"schema_version": "1.0", "capabilities": []}
    )
    state.status = Status.CHECKPOINT_READY
    checkpoint, _ = create_checkpoint(state, tmp_path / "checkpoint", next_action="continue")
    Draft202012Validator(schemas["checkpoint.schema"]).validate(
        json.loads(checkpoint.read_text(encoding="utf-8"))
    )


def _run_script(script: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "skills" / "stackmarshal" / "scripts" / script), *args],
        cwd=cwd or ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_dependency_free_skill_fallback_commands(tmp_path: Path) -> None:
    invocation = _run_script("stackmarshal_core.py", "invocation", "StackMarshalを使って実装して")
    assert invocation.returncode == 0
    assert json.loads(invocation.stdout)["mode"] == "build"

    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps({"id": "x", "scores": {"requirement_fit": 1}, "risks": []}),
        encoding="utf-8",
    )
    scored = _run_script("stackmarshal_core.py", "score", str(candidate))
    assert scored.returncode == 0
    assert json.loads(scored.stdout)["total"] == 30.0

    failure = tmp_path / "failure.json"
    failure.write_text(json.dumps({"message": "token=do-not-log"}), encoding="utf-8")
    fingerprint = _run_script("stackmarshal_core.py", "fingerprint", str(failure))
    assert len(json.loads(fingerprint.stdout)["fingerprint"]) == 64

    budget_file = tmp_path / "budget.json"
    budget_file.write_text(json.dumps({"limits": {"x": 1}, "used": {"x": 2}}), encoding="utf-8")
    budget = _run_script("stackmarshal_core.py", "budget", str(budget_file))
    assert json.loads(budget.stdout)["valid"] is False

    progress_file = tmp_path / "progress.json"
    progress_file.write_text(
        json.dumps({"previous": {"tests_passed": 1}, "current": {"tests_passed": 2}}),
        encoding="utf-8",
    )
    progress = _run_script("stackmarshal_core.py", "progress", str(progress_file))
    assert json.loads(progress.stdout)["improved"] is True

    checkpoint_input = tmp_path / "checkpoint-input.json"
    checkpoint_input.write_text(
        json.dumps(
            {
                "run_id": "run-12345678",
                "project_identity": "identity",
                "status": "CHECKPOINT_READY",
                "current_phase": "CHECKPOINTING",
                "next_action": "continue",
            }
        ),
        encoding="utf-8",
    )
    checkpoint_output = tmp_path / "checkpoint.json"
    checkpoint = _run_script(
        "stackmarshal_core.py",
        "checkpoint",
        str(checkpoint_input),
        "--output",
        str(checkpoint_output),
    )
    assert checkpoint.returncode == 0 and checkpoint_output.exists()


def test_dependency_free_fallback_rejects_project_local_signing_key(tmp_path: Path) -> None:
    checkpoint_input = tmp_path / "checkpoint-input.json"
    checkpoint_input.write_text(
        json.dumps(
            {
                "run_id": "run-12345678",
                "project_identity": "identity",
                "status": "CHECKPOINT_READY",
                "current_phase": "CHECKPOINTING",
                "next_action": "continue",
            }
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["STACKMARSHAL_STATE_HOME"] = str(tmp_path / ".stackmarshal-user")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills" / "stackmarshal" / "scripts" / "stackmarshal_core.py"),
            "checkpoint",
            str(checkpoint_input),
            "--output",
            str(tmp_path / "checkpoint.json"),
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "outside the project" in result.stderr


def test_installed_cli_wrappers_forward_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    started = _run_script(
        "init_run.py",
        "--root",
        str(project),
        "--invocation",
        "Use StackMarshal to build",
    )
    assert started.returncode == 0, started.stderr
    payload = json.loads(started.stdout)
    state_path = Path(payload["state"])
    assert state_path.exists()

    validated = _run_script("validate_state.py", "--root", str(project), str(state_path))
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout)["valid"] is True


def test_skill_contract_and_document_links() -> None:
    skill_root = ROOT / "skills" / "stackmarshal"
    skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    assert skill_text.startswith("---\n")
    assert len(skill_text.splitlines()) < 500
    frontmatter = skill_text.split("---", 2)[1]
    assert "name: stackmarshal" in frontmatter
    assert "explicitly names StackMarshal" in frontmatter
    for reference in (
        "workflow.md",
        "research-policy.md",
        "capability-policy.md",
        "acquisition-policy.md",
        "security-policy.md",
        "stop-policy.md",
        "checkpoint-policy.md",
        "output-contract.md",
        "adapter-selection.md",
    ):
        assert (skill_root / "references" / reference).exists()

    for readme in (ROOT / "README.md", ROOT / "README.ja.md"):
        text = readme.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#")):
                continue
            assert (ROOT / target).exists(), f"Broken link in {readme.name}: {target}"
