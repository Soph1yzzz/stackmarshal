from __future__ import annotations

import argparse
import copy
from datetime import UTC, datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=check, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()


def run(*args: str, source_date_epoch: int) -> None:
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    environment["PYTHONHASHSEED"] = "0"
    subprocess.run(args, cwd=ROOT, check=True, env=environment, timeout=300)


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def resolve_release_version(requested: str | None) -> str:
    current = project_version()
    if requested is None:
        return current
    version = requested.removeprefix("v")
    if version != current:
        raise SystemExit(f"Version mismatch: requested {version}, pyproject has {current}")
    return version


def resolve_epoch(explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        return int(configured)
    value = git("show", "-s", "--format=%ct", "HEAD")
    return int(value)


def normalized_time(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, UTC).replace(microsecond=0)


def safe_regular_file(root: Path, path: Path) -> Path:
    """Return a contained regular file without following repository symlinks."""
    resolved_root = root.resolve(strict=True)
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Release input may not be a symlink: {relative.as_posix()}")
    resolved = path.resolve(strict=True)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"Release input escapes its root: {relative.as_posix()}")
    if not resolved.is_file():
        raise ValueError(f"Release input is not a regular file: {relative.as_posix()}")
    return resolved


def zip_tree(source: Path, destination: Path, prefix: str, epoch: int) -> None:
    # ZIP timestamps cannot predate 1980-01-01.
    zip_time = normalized_time(max(epoch, 315532800)).timetuple()[:6]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative_source = path.relative_to(source)
            if "__pycache__" in relative_source.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            safe_path = safe_regular_file(source, path)
            relative = (Path(prefix) / relative_source).as_posix()
            info = zipfile.ZipInfo(relative, date_time=zip_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                safe_path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def tracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, timeout=30
    ).stdout
    return [Path(item.decode("utf-8")) for item in output.split(b"\0") if item]


def validate_tracked_files() -> None:
    for relative in tracked_files():
        safe_regular_file(ROOT, ROOT / relative)


def source_archive(destination: Path, version: str, epoch: int) -> None:
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for relative in tracked_files():
            path = safe_regular_file(ROOT, ROOT / relative)
            archive_name = (Path(f"stackmarshal-{version}") / relative).as_posix()
            info = archive.gettarinfo(str(path), arcname=archive_name)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = epoch
            info.mode = 0o644
            with path.open("rb") as handle:
                archive.addfile(info, handle)
    with destination.open("wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9
    ) as compressed:
        compressed.write(tar_buffer.getvalue())


def normalize_tar_gz(path: Path, epoch: int) -> None:
    """Rewrite an sdist with stable metadata and gzip headers."""
    entries: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(path, "r:gz") as source:
        for member in source.getmembers():
            payload: bytes | None = None
            if member.isfile():
                extracted = source.extractfile(member)
                if extracted is None:
                    raise ValueError(f"Could not read archive member: {member.name}")
                payload = extracted.read()
            normalized = copy.copy(member)
            normalized.uid = 0
            normalized.gid = 0
            normalized.uname = ""
            normalized.gname = ""
            normalized.mtime = epoch
            normalized.pax_headers = {}
            normalized.mode = 0o755 if normalized.isdir() else 0o644
            entries.append((normalized, payload))
    temporary = path.with_suffix(path.suffix + ".tmp")
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for member, payload in sorted(entries, key=lambda item: item[0].name):
            archive.addfile(member, io.BytesIO(payload) if payload is not None else None)
    with temporary.open("wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9
    ) as compressed:
        compressed.write(tar_buffer.getvalue())
    temporary.replace(path)


def write_text_lf(path: Path, text: str) -> None:
    """Write portable release metadata with LF line endings on every platform."""
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, data: object) -> None:
    write_text_lf(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_checksums(path: Path, targets: list[Path]) -> None:
    write_text_lf(path, "".join(f"{sha256(target)}  {target.name}\n" for target in targets))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic StackMarshal release assets")
    parser.add_argument(
        "version",
        nargs="?",
        help="Release version; defaults to [project].version from pyproject.toml",
    )
    parser.add_argument("--source-date-epoch", type=int)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    version = resolve_release_version(args.version)
    if not args.allow_dirty and git("status", "--porcelain"):
        raise SystemExit("Refusing to build a release from a dirty Git worktree")

    validate_tracked_files()
    epoch = resolve_epoch(args.source_date_epoch)
    created_at = normalized_time(epoch).isoformat()
    git_head = git("rev-parse", "HEAD")
    release = ROOT / "release"
    dist = ROOT / "dist"
    for directory in (release, dist):
        if directory.exists():
            shutil.rmtree(directory)
    release.mkdir()

    run(sys.executable, "-m", "build", source_date_epoch=epoch)
    for archive in dist.glob("*.tar.gz"):
        normalize_tar_gz(archive, epoch)
    run(sys.executable, "-m", "twine", "check", *[str(path) for path in sorted(dist.iterdir())], source_date_epoch=epoch)
    for artifact in sorted(dist.iterdir()):
        shutil.copy2(artifact, release / artifact.name)

    skill_zip = release / f"stackmarshal-skill-v{version}.zip"
    zip_tree(ROOT / "skills" / "stackmarshal", skill_zip, "stackmarshal", epoch)
    source_tar = release / f"stackmarshal-source-v{version}.tar.gz"
    source_archive(source_tar, version, epoch)
    for installer_name in ("installer.py", "install.ps1", "install.sh"):
        source = safe_regular_file(ROOT, ROOT / "scripts" / installer_name)
        shutil.copyfile(source, release / installer_name)

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{hashlib.sha256(f'{version}:{git_head}'.encode()).hexdigest()[:32]}",
        "version": 1,
        "metadata": {"timestamp": created_at},
        "components": [
            {
                "type": "application",
                "bom-ref": f"pkg:pypi/stackmarshal@{version}",
                "name": "stackmarshal",
                "version": version,
                "purl": f"pkg:pypi/stackmarshal@{version}",
                "licenses": [{"license": {"id": "Apache-2.0"}}],
            }
        ],
        "dependencies": [{"ref": f"pkg:pypi/stackmarshal@{version}", "dependsOn": []}],
    }
    write_json(release / "stackmarshal-sbom.cdx.json", sbom)
    write_json(
        release / "provenance.json",
        {
            "version": version,
            "created_at": created_at,
            "source_date_epoch": epoch,
            "git_head": git_head,
            "python": sys.version,
            "builder": "scripts/build_release.py",
            "runtime_dependencies": [],
            "dirty_worktree_allowed": bool(args.allow_dirty),
        },
    )

    initial_artifacts = sorted(release.iterdir())
    manifest = {
        "schema_version": "1.0",
        "project": "StackMarshal",
        "version": version,
        "git_head": git_head,
        "source_date_epoch": epoch,
        "artifacts": [
            {"name": path.name, "sha256": sha256(path), "size": path.stat().st_size}
            for path in initial_artifacts
        ],
    }
    write_json(release / "release-manifest.json", manifest)
    checksum_targets = sorted(path for path in release.iterdir() if path.name != "SHA256SUMS")
    write_checksums(release / "SHA256SUMS", checksum_targets)
    print(
        json.dumps(
            {
                "release": str(release),
                "version": version,
                "git_head": git_head,
                "source_date_epoch": epoch,
                "artifacts": [path.name for path in sorted(release.iterdir())],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
