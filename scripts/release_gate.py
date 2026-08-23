from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

try:
    from version_contract import ROOT, check_version_contract, project_version
except ModuleNotFoundError:  # imported by tests as scripts.release_gate
    from scripts.version_contract import ROOT, check_version_contract, project_version

STAGES = ("candidate", "immutable", "published")


class ReleaseGateError(RuntimeError):
    def __init__(self, message: str, checks: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.checks = list(checks)


def _run(command: list[str], *, timeout: int = 600) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    record = {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }
    if result.returncode != 0:
        raise RuntimeError(json.dumps(record, ensure_ascii=False))
    return record


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_release_directory(
    directory: Path,
    version: str,
    *,
    expected_git_head: str | None = None,
) -> dict[str, Any]:
    directory = directory.resolve(strict=True)
    checksum_file = directory / "SHA256SUMS"
    manifest_file = directory / "release-manifest.json"
    provenance_file = directory / "provenance.json"
    if not checksum_file.is_file() or not manifest_file.is_file() or not provenance_file.is_file():
        raise RuntimeError("Release directory is missing checksum, manifest, or provenance metadata")

    checked: list[str] = []
    seen: set[str] = set()
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if "  " not in line:
            raise RuntimeError("Malformed SHA256SUMS entry")
        expected, name = line.split("  ", 1)
        if re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None:
            raise RuntimeError(f"Malformed SHA-256 digest for {name}")
        relative = Path(name)
        if relative.is_absolute() or len(relative.parts) != 1 or relative.name != name or name in {".", ".."}:
            raise RuntimeError(f"Unsafe checksum target name: {name}")
        if name in seen:
            raise RuntimeError(f"Duplicate checksum target: {name}")
        seen.add(name)
        candidate = directory / relative
        if candidate.is_symlink():
            raise RuntimeError(f"Checksum target may not be a symlink: {name}")
        try:
            target = candidate.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(f"Checksum target is missing: {name}") from exc
        if target.parent != directory or not target.is_file():
            raise RuntimeError(f"Checksum target escapes release directory: {name}")
        actual = _sha256(target)
        if actual.lower() != expected.lower():
            raise RuntimeError(f"Checksum mismatch for {name}: {actual} != {expected}")
        checked.append(name)

    expected_names = {
        "install.ps1",
        "install.sh",
        "installer.py",
        "provenance.json",
        "release-manifest.json",
        f"stackmarshal-{version}-py3-none-any.whl",
        f"stackmarshal-{version}.tar.gz",
        "stackmarshal-sbom.cdx.json",
        f"stackmarshal-skill-v{version}.zip",
        f"stackmarshal-source-v{version}.tar.gz",
    }
    actual_names: set[str] = set()
    for candidate in directory.iterdir():
        if candidate.name == "SHA256SUMS":
            continue
        if candidate.is_symlink() or not candidate.is_file():
            raise RuntimeError(f"Unexpected non-regular release entry: {candidate.name}")
        actual_names.add(candidate.name)
    if seen != expected_names or actual_names != expected_names:
        raise RuntimeError(
            "Release asset set does not match the v1 contract: "
            f"checksums={sorted(seen)}, files={sorted(actual_names)}, expected={sorted(expected_names)}"
        )

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
    if manifest.get("version") != version or provenance.get("version") != version:
        raise RuntimeError("Release manifest/provenance version does not match project version")
    if provenance.get("dirty_worktree_allowed") is not False:
        raise RuntimeError("Release provenance must come from a clean immutable worktree")
    manifest_head = manifest.get("git_head")
    provenance_head = provenance.get("git_head")
    if not isinstance(manifest_head, str) or manifest_head != provenance_head:
        raise RuntimeError("Release manifest/provenance Git HEAD values do not match")
    if expected_git_head is not None and manifest_head != expected_git_head:
        raise RuntimeError(
            f"Release Git HEAD {manifest_head!r} does not match expected immutable HEAD {expected_git_head!r}"
        )
    coherence = manifest.get("version_coherence")
    if not isinstance(coherence, dict) or coherence.get("coherent") is not True:
        raise RuntimeError("Release manifest does not contain passing version coherence evidence")
    components = coherence.get("components")
    if not isinstance(components, dict) or not components:
        raise RuntimeError("Release manifest version coherence components are missing")
    if any(component_version != version for component_version in components.values()):
        raise RuntimeError("Release manifest component versions do not match project version")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise RuntimeError("Release manifest artifacts list is missing")
    expected_manifest_names = expected_names - {"release-manifest.json"}
    manifest_names: set[str] = set()
    for record in artifacts:
        if not isinstance(record, dict):
            raise RuntimeError("Release manifest artifact record is invalid")
        name = record.get("name")
        if not isinstance(name, str) or name not in expected_manifest_names or name in manifest_names:
            raise RuntimeError(f"Release manifest artifact name is invalid or duplicated: {name!r}")
        manifest_names.add(name)
        target = directory / name
        if record.get("sha256") != _sha256(target) or record.get("size") != target.stat().st_size:
            raise RuntimeError(f"Release manifest artifact metadata mismatch: {name}")
    if manifest_names != expected_manifest_names:
        raise RuntimeError("Release manifest artifact set is incomplete")
    return {
        "directory": str(directory),
        "checksums_verified": len(checked),
        "manifest_version": manifest.get("version"),
        "git_head": manifest.get("git_head"),
        "version_coherence": coherence,
    }


def _safe_output_directory(root: Path, path: Path) -> Path:
    """Validate a root-level build output before deleting or reusing it."""

    resolved_root = root.resolve(strict=True)
    if path.is_symlink():
        raise RuntimeError(f"Build output may not be a symlink: {path.relative_to(root)}")
    if not path.exists():
        if path.parent.resolve(strict=True) != resolved_root:
            raise RuntimeError(f"Build output parent escapes repository root: {path.relative_to(root)}")
        return path
    resolved = path.resolve(strict=True)
    if resolved.parent != resolved_root or not resolved.is_dir():
        raise RuntimeError(f"Build output escapes repository root or is not a directory: {path.relative_to(root)}")
    return path


def _safe_report_directory(root: Path) -> Path:
    """Create the report directory without following repository-escape links."""

    resolved_root = root.resolve(strict=True)
    current = resolved_root
    for part in ("build", "release-gate"):
        candidate = current / part
        if candidate.exists() or candidate.is_symlink():
            if candidate.is_symlink():
                raise RuntimeError(f"Release gate report path may not be a symlink: {candidate}")
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise RuntimeError(f"Release gate report path is invalid: {candidate}") from exc
            if resolved_root not in resolved.parents:
                raise RuntimeError(f"Release gate report path escapes repository root: {candidate}")
            if not resolved.is_dir():
                raise RuntimeError(f"Release gate report path is not a directory: {candidate}")
            current = resolved
        else:
            candidate.mkdir()
            current = candidate
    return current


def _write_report(report: dict[str, Any], *, root: Path = ROOT) -> tuple[Path, Path]:
    directory = _safe_report_directory(root)
    json_path = directory / "release-gate-report.json"
    md_path = directory / "release-gate-report.md"
    if json_path.is_symlink() or md_path.is_symlink():
        raise RuntimeError("Release gate report files may not be symlinks")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    lines = [
        "# StackMarshal Release Gate",
        "",
        f"- stage: `{report['stage']}`",
        f"- version: `{report['version']}`",
        f"- git_head: `{report['git_head']}`",
        f"- clean_worktree_required: `{report['clean_worktree_required']}`",
        f"- result: `{'PASS' if report['passed'] else 'FAIL'}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- `{check['name']}`: `{check['status']}`")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return json_path, md_path


def run_gate(stage: str, *, release_dir: Path | None = None) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"Unknown release gate stage: {stage}")
    version = project_version()
    git_head = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    clean_required = stage in {"immutable", "published"}
    if clean_required and status:
        raise RuntimeError(f"{stage} release gate requires a clean worktree")

    checks: list[dict[str, Any]] = []

    def record(name: str, action: Any) -> Any:
        try:
            detail = action()
        except Exception as exc:
            checks.append({"name": name, "status": "FAIL", "detail": str(exc)})
            raise ReleaseGateError(str(exc), checks) from exc
        checks.append({"name": name, "status": "PASS", "detail": detail})
        return detail

    def require_version_contract() -> dict[str, Any]:
        contract = check_version_contract()
        if not contract["coherent"]:
            raise RuntimeError(f"Version contract failed: {contract['errors']}")
        return contract

    record("version_contract", require_version_contract)
    record("git_diff_check", lambda: _run(["git", "diff", "--check"]))
    record("ruff", lambda: _run([sys.executable, "-m", "ruff", "check", "."]))
    record("mypy_strict", lambda: _run([sys.executable, "-m", "mypy", "src/stackmarshal"]))
    record(
        "pytest_coverage",
        lambda: _run([sys.executable, "-m", "coverage", "run", "--source=src/stackmarshal", "-m", "pytest"]),
    )
    record("coverage_gate", lambda: _run([sys.executable, "-m", "coverage", "report", "--fail-under=85"]))

    if stage == "candidate":
        build = _safe_output_directory(ROOT, ROOT / "build")
        dist = _safe_output_directory(ROOT, ROOT / "dist")
        for directory in (build, dist):
            if directory.exists():
                shutil.rmtree(directory)
        record("package_build", lambda: _run([sys.executable, "-m", "build"]))
        artifacts = sorted((ROOT / "dist").glob("*"))
        record("twine", lambda: _run([sys.executable, "-m", "twine", "check", *[str(path) for path in artifacts]]))
    elif stage == "immutable":
        record("deterministic_release_build", lambda: _run([sys.executable, "scripts/build_release.py"]))
        record(
            "release_integrity",
            lambda: verify_release_directory(ROOT / "release", version, expected_git_head=git_head),
        )
        record("installer_smoke", lambda: _run([sys.executable, "scripts/smoke_installer.py"], timeout=900))
    else:
        tag = f"v{version}"
        record("tag_points_to_head", lambda: _verify_tag(tag, git_head))
        target = (release_dir or ROOT / "release").resolve()
        record(
            "published_asset_integrity",
            lambda: verify_release_directory(target, version, expected_git_head=git_head),
        )

    return {
        "schema_version": "1.0",
        "stage": stage,
        "version": version,
        "git_head": git_head,
        "worktree_dirty": bool(status),
        "clean_worktree_required": clean_required,
        "created_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "checks": checks,
    }


def _verify_tag(tag: str, git_head: str) -> dict[str, str]:
    tag_head = _git("rev-list", "-n", "1", tag)
    if tag_head != git_head:
        raise RuntimeError(f"Tag {tag} resolves to {tag_head}, expected {git_head}")
    return {"tag": tag, "git_head": tag_head}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the staged StackMarshal release integrity contract")
    parser.add_argument("--stage", choices=STAGES, default="candidate")
    parser.add_argument(
        "--release-dir",
        type=Path,
        help="Downloaded published asset directory for --stage published",
    )
    args = parser.parse_args()
    report: dict[str, Any]
    try:
        report = run_gate(args.stage, release_dir=args.release_dir)
    except Exception as exc:
        report = {
            "schema_version": "1.0",
            "stage": args.stage,
            "version": project_version(),
            "git_head": _git("rev-parse", "HEAD"),
            "clean_worktree_required": args.stage in {"immutable", "published"},
            "passed": False,
            "error": str(exc),
            "checks": getattr(exc, "checks", []),
        }
        json_path, md_path = _write_report(report)
        print(json.dumps({"passed": False, "report": str(json_path), "markdown": str(md_path), "error": str(exc)}, indent=2))
        return 2
    json_path, md_path = _write_report(report)
    print(json.dumps({"passed": True, "report": str(json_path), "markdown": str(md_path), "stage": args.stage}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
