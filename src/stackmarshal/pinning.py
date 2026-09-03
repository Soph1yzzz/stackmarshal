from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import urllib.parse
import urllib.request

REPOSITORY = "Soph1yzzz/stackmarshal"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}.git"
API_BASE = f"https://api.github.com/repos/{REPOSITORY}"
RELEASE_BASE = f"https://github.com/{REPOSITORY}/releases/download"
VERSION_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CHECKSUM_RE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]*)$")
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_BOOTSTRAP_BYTES = 2 * 1024 * 1024


class PinError(RuntimeError):
    pass


def normalize_version(value: str) -> str:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise PinError(f"Invalid version: {value!r}; expected latest or vMAJOR.MINOR.PATCH")
    return ".".join(match.groups())


def _validate_https_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise PinError(f"Unsafe download URL: {url}")


def _download_bytes(url: str, *, limit: int) -> bytes:
    _validate_https_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "StackMarshal-Pin/1"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            _validate_https_url(response.geturl())
            chunks: list[bytes] = []
            total = 0
            while chunk := response.read(64 * 1024):
                total += len(chunk)
                if total > limit:
                    raise PinError(f"Download exceeds {limit} bytes: {url}")
                chunks.append(chunk)
    except PinError:
        raise
    except Exception as exc:
        raise PinError(f"Download failed: {url}: {exc}") from exc
    payload = b"".join(chunks)
    if not payload:
        raise PinError(f"Downloaded file is empty: {url}")
    return payload


def _download_json(url: str) -> dict[str, Any]:
    try:
        payload = json.loads(_download_bytes(url, limit=MAX_METADATA_BYTES).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PinError(f"Invalid GitHub release metadata: {exc}") from exc
    if not isinstance(payload, dict):
        raise PinError("GitHub release metadata must be a JSON object")
    return payload


def resolve_pin_target(requested: str) -> str:
    value = requested.strip()
    if not value:
        raise PinError("Pin target is required")
    if value == "latest":
        release = _download_json(f"{API_BASE}/releases/latest")
    else:
        version = normalize_version(value)
        release = _download_json(f"{API_BASE}/releases/tags/v{version}")

    if release.get("draft") is True or release.get("prerelease") is True:
        raise PinError("Pin target must be a published stable GitHub Release")
    tag = release.get("tag_name")
    if not isinstance(tag, str):
        raise PinError("GitHub Release is missing tag_name")
    version = normalize_version(tag)
    if value != "latest" and version != normalize_version(value):
        raise PinError(f"GitHub Release tag mismatch: requested {value}, observed {tag}")
    return version


def _parse_checksums(text: str) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip("\r")
        if not line:
            continue
        match = CHECKSUM_RE.fullmatch(line)
        if not match:
            raise PinError(f"Malformed SHA256SUMS line {line_number}")
        digest, name = match.groups()
        if name in checksums:
            raise PinError(f"Duplicate checksum entry: {name}")
        checksums[name] = digest
    if not checksums:
        raise PinError("SHA256SUMS is empty")
    return checksums


def _verified_bootstrap(version: str) -> tuple[str, bytes]:
    script_name = "install.ps1" if os.name == "nt" else "install.sh"
    release_base = f"{RELEASE_BASE}/v{version}"
    checksums_raw = _download_bytes(f"{release_base}/SHA256SUMS", limit=MAX_METADATA_BYTES)
    try:
        checksums = _parse_checksums(checksums_raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise PinError("SHA256SUMS is not UTF-8") from exc
    expected = checksums.get(script_name)
    if expected is None:
        raise PinError(f"Release checksum is missing for {script_name}")
    script = _download_bytes(f"{release_base}/{script_name}", limit=MAX_BOOTSTRAP_BYTES)
    actual = hashlib.sha256(script).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise PinError(f"Checksum mismatch for {script_name}")
    return script_name, script


def _platform_shell() -> str:
    if os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT")
        if system_root:
            candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            if candidate.is_file() and not candidate.is_symlink():
                return str(candidate)
        shell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if shell is None:
            raise PinError("PowerShell was not found")
        return shell
    for candidate in (Path("/bin/bash"), Path("/usr/bin/bash")):
        if candidate.is_file() and not candidate.is_symlink():
            return str(candidate)
    shell = shutil.which("bash")
    if shell is None:
        raise PinError("bash was not found")
    return shell


def install_pin(
    requested: str,
    *,
    assume_yes: bool = False,
    force: bool = False,
    allow_downgrade: bool = False,
    no_path: bool = False,
) -> str:
    version = resolve_pin_target(requested)
    script_name, script = _verified_bootstrap(version)
    with tempfile.TemporaryDirectory(prefix="stackmarshal-pin-") as temporary:
        path = Path(temporary) / script_name
        path.write_bytes(script)
        shell = _platform_shell()
        if os.name == "nt":
            command = [shell, "-NoProfile", "-File", str(path), "-Version", f"v{version}"]
            if assume_yes:
                command.append("-Yes")
            if force:
                command.append("-Force")
            if allow_downgrade:
                command.append("-AllowDowngrade")
            if no_path:
                command.append("-NoPath")
        else:
            command = [shell, str(path), "--version", f"v{version}"]
            if assume_yes:
                command.append("--yes")
            if force:
                command.append("--force")
            if allow_downgrade:
                command.append("--allow-downgrade")
            if no_path:
                command.append("--no-path")
        environment = os.environ.copy()
        environment.pop("STACKMARSHAL_RELEASE_BASE_PREFIX", None)
        environment.pop("STACKMARSHAL_REPOSITORY_URL", None)
        result = subprocess.run(command, check=False, env=environment)
    if result.returncode != 0:
        raise PinError(f"StackMarshal installer exited with code {result.returncode}")
    return version
