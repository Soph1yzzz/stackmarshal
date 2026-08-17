from __future__ import annotations

import gzip
import hashlib
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
import pytest

from stackmarshal.checkpoint import create_checkpoint
from stackmarshal.config import default_config
from stackmarshal.constants import Mode, Status, __version__
from stackmarshal.state import create_run

ROOT = Path(__file__).resolve().parents[1]


def _load_script_module(name: str) -> object:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"stackmarshal_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_release_module() -> object:
    path = ROOT / "scripts" / "build_release.py"
    spec = importlib.util.spec_from_file_location("stackmarshal_build_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_contract_uses_pyproject_as_authority() -> None:
    module = _load_script_module("version_contract")
    result = module.check_version_contract(ROOT)  # type: ignore[attr-defined]
    assert result["coherent"] is True
    assert result["authority"] == "pyproject.toml:[project].version"
    assert result["version"] == __version__
    assert set(result["components"].values()) == {__version__}

    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python scripts/version_contract.py --check" in workflow
    smoke = (ROOT / "scripts" / "smoke_installer.py").read_text(encoding="utf-8")
    assert f'VERSION = "{__version__}"' not in smoke
    assert "VERSION = project_version()" in smoke


def test_version_contract_sync_updates_only_current_mirrors(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src" / "stackmarshal").mkdir(parents=True)
    (root / "skills" / "stackmarshal").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "2.3.4"\n', encoding="utf-8")
    (root / "src" / "stackmarshal" / "constants.py").write_text('__version__ = "1.1.1"\n', encoding="utf-8")
    (root / "skills" / "stackmarshal" / "SKILL.md").write_text(
        '---\nmetadata:\n  version: "1.1.1"\n---\n'
        'host-ready --version "1.1.1"\n'
        'doctor --host-skill-version "1.1.1"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "release https://example.invalid/releases/download/v1.1.1/install.sh --version v1.1.1\n"
        "runtime Python 3.11.8 must remain unrelated\n",
        encoding="utf-8",
    )
    (root / "README.ja.md").write_text(
        "$skill-installer install https://example.invalid/tree/v1.1.1/skills/stackmarshal\n"
        "stackmarshal doctor --host-skill-version 1.1.1\n"
        "runtime Python 3.11.8 must remain unrelated\n",
        encoding="utf-8",
    )
    historical = root / "docs" / "RELEASE_NOTES_v1.1.1.md"
    historical.write_text("historical v1.1.1\n", encoding="utf-8")

    module = _load_script_module("version_contract")
    changed = module.sync_version_mirrors(root)  # type: ignore[attr-defined]
    result = module.check_version_contract(root)  # type: ignore[attr-defined]
    assert result["coherent"] is True
    assert result["version"] == "2.3.4"
    assert set(changed) == {
        "README.ja.md",
        "README.md",
        "skills/stackmarshal/SKILL.md",
        "src/stackmarshal/constants.py",
    }
    assert "releases/download/v2.3.4/install.sh" in (root / "README.md").read_text(encoding="utf-8")
    assert "--version v2.3.4" in (root / "README.md").read_text(encoding="utf-8")
    assert "/tree/v2.3.4/skills/stackmarshal" in (root / "README.ja.md").read_text(encoding="utf-8")
    assert "host-skill-version 2.3.4" in (root / "README.ja.md").read_text(encoding="utf-8")
    assert "Python 3.11.8" in (root / "README.md").read_text(encoding="utf-8")
    assert "Python 3.11.8" in (root / "README.ja.md").read_text(encoding="utf-8")
    assert historical.read_text(encoding="utf-8") == "historical v1.1.1\n"


def _write_release_fixture_checksums(directory: Path) -> None:
    targets = sorted(path for path in directory.iterdir() if path.name != "SHA256SUMS")
    text = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in targets
    )
    (directory / "SHA256SUMS").write_text(text, encoding="utf-8")


def _write_release_gate_fixture(directory: Path, version: str) -> None:
    directory.mkdir()
    payload_names = {
        "install.ps1",
        "install.sh",
        "installer.py",
        f"stackmarshal-{version}-py3-none-any.whl",
        f"stackmarshal-{version}.tar.gz",
        "stackmarshal-sbom.cdx.json",
        f"stackmarshal-skill-v{version}.zip",
        f"stackmarshal-source-v{version}.tar.gz",
    }
    for name in sorted(payload_names):
        (directory / name).write_bytes(f"fixture:{name}".encode())
    (directory / "provenance.json").write_text(
        json.dumps({"version": version, "git_head": "deadbeef", "dirty_worktree_allowed": False}),
        encoding="utf-8",
    )
    manifest_artifacts = []
    for path in sorted(directory.iterdir()):
        manifest_artifacts.append(
            {
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
    (directory / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": version,
                "git_head": "deadbeef",
                "version_coherence": {
                    "coherent": True,
                    "components": {
                        "project": version,
                        "core": version,
                        "skill": version,
                        "installer_smoke": version,
                    },
                },
                "artifacts": manifest_artifacts,
            }
        ),
        encoding="utf-8",
    )
    _write_release_fixture_checksums(directory)


def test_release_gate_accepts_complete_clean_fixture(tmp_path: Path) -> None:
    module = _load_script_module("release_gate")
    release = tmp_path / "release"
    _write_release_gate_fixture(release, __version__)
    result = module.verify_release_directory(  # type: ignore[attr-defined]
        release,
        __version__,
        expected_git_head="deadbeef",
    )
    assert result["checksums_verified"] == 10
    assert result["git_head"] == "deadbeef"


def test_release_gate_rejects_checksum_path_traversal_and_duplicate_entries(tmp_path: Path) -> None:
    module = _load_script_module("release_gate")
    release = tmp_path / "release"
    _write_release_gate_fixture(release, __version__)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()

    (release / "SHA256SUMS").write_text(f"{digest}  ../secret.txt\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Unsafe checksum target name"):
        module.verify_release_directory(release, __version__)  # type: ignore[attr-defined]

    target = release / "install.ps1"
    artifact_digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (release / "SHA256SUMS").write_text(
        f"{artifact_digest}  install.ps1\n{artifact_digest}  install.ps1\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="Duplicate checksum target"):
        module.verify_release_directory(release, __version__)  # type: ignore[attr-defined]


def test_release_gate_rejects_forged_component_coherence_and_wrong_head(tmp_path: Path) -> None:
    module = _load_script_module("release_gate")
    release = tmp_path / "release"
    _write_release_gate_fixture(release, __version__)
    manifest = json.loads((release / "release-manifest.json").read_text(encoding="utf-8"))
    manifest["version_coherence"]["components"]["skill"] = "0.0.0"
    (release / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _write_release_fixture_checksums(release)
    with pytest.raises(RuntimeError, match="component versions do not match"):
        module.verify_release_directory(release, __version__)  # type: ignore[attr-defined]

    manifest["version_coherence"]["components"]["skill"] = __version__
    (release / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _write_release_fixture_checksums(release)
    with pytest.raises(RuntimeError, match="expected immutable HEAD"):
        module.verify_release_directory(  # type: ignore[attr-defined]
            release,
            __version__,
            expected_git_head="cafebabe",
        )


def test_release_version_defaults_to_pyproject_and_keeps_mismatch_guard() -> None:
    module = _load_release_module()
    current = module.project_version()  # type: ignore[attr-defined]
    assert module.resolve_release_version(None) == current  # type: ignore[attr-defined]
    assert module.resolve_release_version(f"v{current}") == current  # type: ignore[attr-defined]
    try:
        module.resolve_release_version("0.0.0")  # type: ignore[attr-defined]
    except SystemExit as exc:
        assert str(exc) == f"Version mismatch: requested 0.0.0, pyproject has {current}"
    else:
        raise AssertionError("Explicit release version mismatch must fail closed")


def test_ci_release_build_uses_shell_neutral_project_version_resolution() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release_commands = [
        line.strip() for line in workflow.splitlines() if "run: python scripts/build_release.py" in line
    ]
    assert release_commands == ["run: python scripts/build_release.py"]
    assert 'os: [ubuntu-latest, macos-latest, windows-latest]' in workflow
    assert 'python-version: ["3.11", "3.12", "3.13"]' in workflow
    assert "if: matrix.python-version == '3.11'" in workflow


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
    Draft202012Validator(schemas["task-graph.schema"]).validate(
        {
            "schema_version": "1.0",
            "tasks": [
                {
                    "id": "verify",
                    "summary": "verify",
                    "mandatory": True,
                    "acceptance": ["tests pass"],
                    "status": "done",
                    "attempts": 1,
                    "evidence": ["pytest passed"],
                }
            ],
        }
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


def test_skill_fallback_blocks_stale_host_until_matching_version_acknowledges_restart(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    marker = codex_home / ".stackmarshal-restart-required.json"
    marker.write_text(
        json.dumps({"schema_version": 1, "version": __version__}),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    script = ROOT / "skills" / "stackmarshal" / "scripts" / "stackmarshal_core.py"

    stale = subprocess.run(
        [sys.executable, str(script), "invocation", "$stackmarshal build"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert stale.returncode == 0
    stale_payload = json.loads(stale.stdout)
    assert stale_payload["triggered"] is False
    assert stale_payload["restart_required"] is True
    assert stale_payload["target_version"] == __version__
    assert marker.exists()

    wrong = subprocess.run(
        [sys.executable, str(script), "host-ready", "--version", "1.1.0"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert wrong.returncode == 0
    wrong_payload = json.loads(wrong.stdout)
    assert wrong_payload["ready"] is False
    assert wrong_payload["restart_required"] is True
    assert marker.exists()

    ready = subprocess.run(
        [sys.executable, str(script), "host-ready", "--version", __version__],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert ready.returncode == 0
    ready_payload = json.loads(ready.stdout)
    assert ready_payload["ready"] is True
    assert ready_payload["acknowledged_restart"] is True
    assert not marker.exists()

    invoked = subprocess.run(
        [sys.executable, str(script), "invocation", "$stackmarshal build"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert invoked.returncode == 0
    assert json.loads(invoked.stdout)["triggered"] is True


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
