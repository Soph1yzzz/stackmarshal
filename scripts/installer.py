from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
from typing import Any
import urllib.parse
import urllib.request
import unicodedata
import uuid
import zipfile

MIN_PYTHON = (3, 11)
VERSION_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CHECKSUM_RE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]*)$")
MANAGED_PROFILE_START = "# >>> stackmarshal >>>"
MANAGED_PROFILE_END = "# <<< stackmarshal <<<"
REPOSITORY_URL = "https://github.com/Soph1yzzz/stackmarshal.git"
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_SKILL_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_SKILL_FILES = 2048
MAX_SKILL_MEMBER_BYTES = 16 * 1024 * 1024
MAX_SKILL_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_TREE_FILES = 10_000
MAX_TREE_BYTES = 256 * 1024 * 1024
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class InstallError(RuntimeError):
    pass


def normalize_version(value: str) -> str:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise InstallError(f"Invalid version: {value!r}; expected vMAJOR.MINOR.PATCH")
    return ".".join(match.groups())


def version_tuple(value: str) -> tuple[int, int, int]:
    normalized = normalize_version(value)
    return tuple(int(part) for part in normalized.split("."))  # type: ignore[return-value]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksums(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip("\r")
        if not line:
            continue
        match = CHECKSUM_RE.fullmatch(line)
        if not match:
            raise InstallError(f"Malformed SHA256SUMS line {number}")
        digest, name = match.groups()
        if name in result:
            raise InstallError(f"Duplicate checksum entry: {name}")
        result[name] = digest
    if not result:
        raise InstallError("SHA256SUMS is empty")
    return result


def verify_checksum(path: Path, checksums: dict[str, str]) -> str:
    expected = checksums.get(path.name)
    if expected is None:
        raise InstallError(f"Release checksum is missing for {path.name}")
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected):
        raise InstallError(f"Checksum mismatch for {path.name}")
    return actual


def validate_download_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    if parsed.username or parsed.password:
        raise InstallError("Download URLs may not contain credentials")
    if not parsed.hostname:
        raise InstallError(f"Download URL has no host: {url}")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in loopback_hosts):
        raise InstallError(f"Unsupported download URL: {url}")
    return parsed


def download(url: str, destination: Path) -> None:
    validate_download_url(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "StackMarshal-Installer/1"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:  # noqa: S310
            validate_download_url(response.geturl())
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise InstallError(f"Download exceeds {MAX_DOWNLOAD_BYTES} bytes: {url}")
                output.write(chunk)
    except InstallError:
        raise
    except Exception as exc:  # urllib exposes several platform-specific exception types.
        raise InstallError(f"Download failed: {url}: {exc}") from exc
    if not destination.is_file() or destination.stat().st_size == 0:
        raise InstallError(f"Downloaded file is empty: {destination.name}")


def _assert_contained(path: Path, root: Path, *, allow_root: bool = False) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved == resolved_root:
        if allow_root:
            return resolved
        raise InstallError(f"Refusing to operate on managed root itself: {resolved}")
    if resolved_root not in resolved.parents:
        raise InstallError(f"Path escapes managed root: {resolved}")
    return resolved


def safe_remove(path: Path, root: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    resolved = _assert_contained(path, root)
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        raise InstallError(f"Refusing to remove unsupported path: {path}")


def tree_hash(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise InstallError(f"Expected a regular directory: {root}")
    digest = hashlib.sha256()
    file_count = 0
    total_size = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise InstallError(f"Managed tree may not contain symlinks: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise InstallError(f"Managed tree contains a non-regular file: {relative}")
        file_count += 1
        total_size += path.stat().st_size
        if file_count > MAX_TREE_FILES or total_size > MAX_TREE_BYTES:
            raise InstallError("Managed tree exceeds the bounded file-count or size limit")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_archive_component(component: str) -> None:
    if not component or component in {".", ".."}:
        raise InstallError(f"Unsafe empty or relative archive component: {component!r}")
    if component.endswith((" ", ".")) or ":" in component:
        raise InstallError(f"Non-portable archive component: {component!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in component):
        raise InstallError(f"Control character in archive component: {component!r}")
    stem = component.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        raise InstallError(f"Reserved Windows archive component: {component!r}")


def safe_extract_skill_zip(archive_path: Path, destination: Path) -> Path:
    if archive_path.is_symlink() or not archive_path.is_file():
        raise InstallError(f"Skill archive is not a regular file: {archive_path}")
    if archive_path.stat().st_size > MAX_SKILL_ARCHIVE_BYTES:
        raise InstallError("Skill archive exceeds the compressed-size limit")
    destination.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_SKILL_FILES:
            raise InstallError("Skill archive exceeds the file-count limit")
        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > MAX_SKILL_UNCOMPRESSED_BYTES:
            raise InstallError("Skill archive exceeds the uncompressed-size limit")
        for info in infos:
            if info.flag_bits & 0x1:
                raise InstallError(f"Encrypted Skill archive entry is not supported: {info.filename}")
            if info.file_size > MAX_SKILL_MEMBER_BYTES:
                raise InstallError(f"Skill archive entry exceeds the member-size limit: {info.filename}")
            if info.file_size > 1024 * 1024 and info.file_size > max(info.compress_size, 1) * 200:
                raise InstallError(f"Suspicious Skill archive compression ratio: {info.filename}")
            if "\\" in info.filename:
                raise InstallError(f"Backslashes are not allowed in Skill archive paths: {info.filename}")
            pure = PurePosixPath(info.filename)
            if pure.is_absolute() or not pure.parts or pure.parts[0] != "stackmarshal" or ".." in pure.parts:
                raise InstallError(f"Unsafe Skill archive path: {info.filename}")
            for component in pure.parts:
                _validate_archive_component(component)
            normalized = pure.as_posix().rstrip("/")
            duplicate_key = unicodedata.normalize("NFC", normalized).casefold()
            if duplicate_key in seen:
                raise InstallError(f"Duplicate or case-colliding Skill archive path: {info.filename}")
            seen.add(duplicate_key)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise InstallError(f"Skill archive may not contain symlinks: {info.filename}")
            target = destination.joinpath(*pure.parts)
            _assert_contained(target, destination)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if mode and not stat.S_ISREG(mode):
                raise InstallError(f"Skill archive contains a non-regular file: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    skill = destination / "stackmarshal"
    if not (skill / "SKILL.md").is_file():
        raise InstallError("Skill archive does not contain stackmarshal/SKILL.md")
    tree_hash(skill)
    return skill


def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(data)
    if mode is not None:
        temporary.chmod(mode)
    os.replace(temporary, path)


def atomic_write_text(path: Path, text: str, *, executable: bool = False) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode=0o755 if executable else None)


@dataclass(frozen=True)
class FileSnapshot:
    existed: bool
    data: bytes | None
    mode: int | None


def snapshot_file(path: Path) -> FileSnapshot:
    if not path.exists() and not path.is_symlink():
        return FileSnapshot(False, None, None)
    if path.is_symlink() or not path.is_file():
        raise InstallError(f"Managed file path is not a regular file: {path}")
    return FileSnapshot(True, path.read_bytes(), stat.S_IMODE(path.stat().st_mode))


def restore_file(path: Path, snapshot: FileSnapshot, managed_root: Path) -> None:
    _assert_contained(path, managed_root)
    if not snapshot.existed:
        if path.exists() or path.is_symlink():
            safe_remove(path, managed_root)
        return
    if snapshot.data is None:
        raise InstallError(f"Invalid file snapshot for {path}")
    atomic_write_bytes(path, snapshot.data, mode=snapshot.mode)


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"Could not read installer state: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InstallError("Installer state must be a JSON object")
    return data


def write_state(path: Path, state: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def _tty_stream() -> Any:
    candidates = ["CONIN$"] if os.name == "nt" else ["/dev/tty"]
    for candidate in candidates:
        try:
            return open(candidate, encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None


def confirm(message: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    stream = _tty_stream()
    if stream is None:
        return False
    try:
        print(f"{message} [y/N] ", end="", flush=True)
        answer = stream.readline().strip().lower()
    finally:
        stream.close()
    return answer in {"y", "yes"}


def default_install_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "StackMarshal"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "stackmarshal"


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def validate_managed_roots(install_root: Path, codex_home: Path) -> None:
    home = Path.home().resolve()
    for label, root in (("install root", install_root), ("Codex home", codex_home)):
        filesystem_root = Path(root.anchor).resolve()
        if root in (filesystem_root, home):
            raise InstallError(f"Refusing unsafe {label}: {root}")
        if root.exists() and not root.is_dir():
            raise InstallError(f"{label.capitalize()} is not a directory: {root}")
    if install_root == codex_home or install_root in codex_home.parents or codex_home in install_root.parents:
        raise InstallError("Install root and Codex home must be separate, non-overlapping directories")


@dataclass
class InstallerLock:
    path: Path
    handle: Any
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.released = True


def acquire_installer_lock(path: Path) -> InstallerLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise InstallError(f"Another StackMarshal installer is using {path.parent}") from exc
    return InstallerLock(path=path, handle=handle)


def venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_checked(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        raise InstallError(f"Command failed ({command[0]}): {details}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallError(f"Could not run {command[0]}: {exc}") from exc


def create_venv(source_python: Path, destination: Path, wheel: Path, version: str) -> Path:
    try:
        subprocess.run(
            [str(source_python), "-I", "-m", "venv", str(destination)],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        raise InstallError(
            "Could not create the dedicated virtual environment. Install the Python venv component "
            f"for Python {sys.version_info.major}.{sys.version_info.minor} and retry. {details}"
        ) from exc
    python = venv_python(destination)
    if not python.is_file():
        raise InstallError("Virtual environment did not create a Python executable")
    run_checked(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-index",
            str(wheel),
        ]
    )
    installed = run_checked([str(python), "-I", "-m", "stackmarshal.cli", "--version"]).stdout.strip()
    if installed != version:
        raise InstallError(f"CLI smoke test returned {installed!r}; expected {version!r}")
    return python


def launcher_text(version: str) -> tuple[str, str]:
    if os.name == "nt":
        return (
            "stackmarshal.cmd",
            "@echo off\r\n"
            f'"%~dp0..\\versions\\v{version}\\venv\\Scripts\\python.exe" -I -m stackmarshal.cli %*\r\n',
        )
    return (
        "stackmarshal",
        "#!/bin/sh\n"
        'SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        f'exec "$SCRIPT_DIR/../versions/v{version}/venv/bin/python" -I -m stackmarshal.cli "$@"\n',
    )


def _broadcast_windows_environment_change() -> None:
    try:
        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            5000,
            ctypes.byref(result),
        )
    except Exception:
        return


def add_windows_user_path(directory: Path) -> bool:
    import winreg

    value = str(directory.resolve())
    normalized = os.path.normcase(value.rstrip("\\/"))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            current, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, value_type = "", winreg.REG_EXPAND_SZ
        entries = [item for item in str(current).split(";") if item]
        filtered = [
            item
            for item in entries
            if os.path.normcase(item.rstrip("\\/")) != normalized
        ]
        updated = ";".join([value, *filtered])
        changed = updated != str(current)
        if changed:
            winreg.SetValueEx(key, "Path", 0, value_type, updated)
    process_entries = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
    process_filtered = [
        item
        for item in process_entries
        if os.path.normcase(item.rstrip("\\/")) != normalized
    ]
    os.environ["PATH"] = os.pathsep.join([value, *process_filtered])
    if changed:
        _broadcast_windows_environment_change()
    return changed


def choose_unix_profile() -> Path | None:
    shell = Path(os.environ.get("SHELL", "")).name
    if shell == "zsh":
        return Path.home() / ".zshrc"
    if shell in {"bash", "sh", "dash", "ksh"}:
        return Path.home() / (".bashrc" if shell == "bash" else ".profile")
    return None


def add_unix_profile_path(directory: Path) -> Path | None:
    profile = choose_unix_profile()
    if profile is None:
        return None
    target = profile.resolve() if profile.exists() else profile
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise InstallError(f"Shell profile is not a regular file: {target}")
    original = target.read_bytes() if target.exists() else b""
    try:
        current = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallError(f"Shell profile is not UTF-8: {target}") from exc
    has_start = MANAGED_PROFILE_START in current
    has_end = MANAGED_PROFILE_END in current
    if has_start != has_end:
        raise InstallError(f"Managed PATH block is malformed in {profile}; repair it before retrying")
    if has_start and has_end:
        return profile
    newline = "\r\n" if b"\r\n" in original else "\n"
    quoted = shlex.quote(str(directory))
    block = newline.join(
        [
            MANAGED_PROFILE_START,
            f"STACKMARSHAL_BIN={quoted}",
            'case ":$PATH:" in',
            '  *":$STACKMARSHAL_BIN:"*) ;;',
            '  *) export PATH="$STACKMARSHAL_BIN:$PATH" ;;',
            "esac",
            "unset STACKMARSHAL_BIN",
            MANAGED_PROFILE_END,
            "",
        ]
    ).encode("utf-8")
    separator = b"" if not original or original.endswith((b"\n", b"\r")) else newline.encode("ascii")
    if target.exists() and target.read_bytes() != original:
        raise InstallError(f"Shell profile changed while it was being updated: {target}")
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    atomic_write_bytes(target, original + separator + block, mode=mode)
    return profile


def install_path(bin_dir: Path, *, assume_yes: bool, no_path: bool) -> tuple[bool, str | None]:
    launcher_name = "stackmarshal.cmd" if os.name == "nt" else "stackmarshal"
    managed_launcher = (bin_dir / launcher_name).resolve()
    resolved_command = shutil.which("stackmarshal")
    if resolved_command is not None:
        resolved_path = Path(resolved_command).resolve()
        if os.path.normcase(str(resolved_path)) == os.path.normcase(str(managed_launcher)):
            return False, None
    if no_path:
        shadow_note = f" The current command resolves to {resolved_command}." if resolved_command else ""
        return False, f"Add {bin_dir} to the front of PATH manually.{shadow_note}"
    if not confirm(f"Add {bin_dir} to your user PATH?", assume_yes=assume_yes):
        return False, f"Add {bin_dir} to PATH manually."
    if os.name == "nt":
        changed = add_windows_user_path(bin_dir)
        resolved_after = shutil.which("stackmarshal")
        note = "Open a new terminal so every process receives the updated PATH."
        if resolved_after is not None and os.path.normcase(str(Path(resolved_after).resolve())) != os.path.normcase(
            str(managed_launcher)
        ):
            note += f" The current process still resolves another command at {resolved_after}."
        return changed, note
    profile = add_unix_profile_path(bin_dir)
    if profile is None:
        return False, f"Add `export PATH=\"{bin_dir}:$PATH\"` to your shell configuration."
    os.environ["PATH"] = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
    return True, f"Open a new shell or run `source {profile}`."


@dataclass
class DirectorySwap:
    destination: Path
    managed_root: Path
    backup: Path | None
    applied: bool = True

    def rollback(self) -> None:
        if not self.applied:
            return
        if self.destination.exists() or self.destination.is_symlink():
            safe_remove(self.destination, self.managed_root)
        if self.backup is not None and (self.backup.exists() or self.backup.is_symlink()):
            os.replace(self.backup, self.destination)
        self.applied = False

    def finalize(self) -> None:
        if self.backup is not None and (self.backup.exists() or self.backup.is_symlink()):
            safe_remove(self.backup, self.managed_root)
        self.applied = False


def apply_directory_swap(staged: Path, destination: Path, managed_root: Path) -> DirectorySwap:
    _assert_contained(staged, managed_root)
    _assert_contained(destination, managed_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if destination.exists() or destination.is_symlink():
        backup = destination.with_name(f".{destination.name}.old-{uuid.uuid4().hex}")
        os.replace(destination, backup)
    try:
        os.replace(staged, destination)
    except Exception:
        if backup is not None and (backup.exists() or backup.is_symlink()):
            os.replace(backup, destination)
        raise
    return DirectorySwap(destination=destination, managed_root=managed_root, backup=backup)


def backup_modified_skill(source: Path, install_root: Path) -> Path:
    backups = install_root / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    for old in backups.glob("stackmarshal-skill-*"):
        safe_remove(old, install_root)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backups / f"stackmarshal-skill-{timestamp}"
    shutil.copytree(source, destination, symlinks=False)
    return destination


def prepare_skill_swap(
    staged_skill: Path,
    destination: Path,
    *,
    install_root: Path,
    previous_hash: str | None,
    assume_yes: bool,
    force: bool,
) -> tuple[str, Path | None, Path]:
    new_hash = tree_hash(staged_skill)
    user_backup: Path | None = None
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise InstallError(f"Existing Skill path is not a regular directory: {destination}")
        current_hash = tree_hash(destination)
        managed_unchanged = hmac.compare_digest(current_hash, new_hash) or (
            previous_hash is not None and hmac.compare_digest(current_hash, previous_hash)
        )
        if not managed_unchanged:
            if not force and not confirm(
                "The existing StackMarshal Skill is not an unchanged installer-managed copy. Back it up and replace it?",
                assume_yes=assume_yes,
            ):
                raise InstallError("Existing Skill was left unchanged; rerun with --force to replace it")
            user_backup = backup_modified_skill(destination, install_root)
    temporary = destination.with_name(f".{destination.name}.new-{uuid.uuid4().hex}")
    if temporary.exists() or temporary.is_symlink():
        safe_remove(temporary, destination.parent)
    try:
        shutil.copytree(staged_skill, temporary, symlinks=False)
        if tree_hash(temporary) != new_hash:
            raise InstallError("Staged Skill copy changed unexpectedly")
    except Exception:
        if temporary.exists() or temporary.is_symlink():
            safe_remove(temporary, destination.parent)
        if user_backup is not None and user_backup.exists():
            safe_remove(user_backup, install_root)
        raise
    return new_hash, user_backup, temporary


def remove_old_versions(versions_root: Path, current: Path, install_root: Path) -> None:
    if not versions_root.exists():
        return
    for child in versions_root.iterdir():
        if child == current:
            continue
        if VERSION_RE.fullmatch(child.name):
            safe_remove(child, install_root)


def targeted_components(*, cli_only: bool, skill_only: bool) -> tuple[str, ...]:
    if cli_only:
        return ("cli",)
    if skill_only:
        return ("skill",)
    return ("cli", "skill")


def installed_component_versions(previous: dict[str, Any], components: tuple[str, ...]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for component in components:
        state = previous.get(component)
        if not isinstance(state, dict):
            continue
        value = state.get("version")
        if isinstance(value, str):
            normalize_version(value)
            versions[component] = value
    return versions


def classify_install_action(version: str, previous_versions: dict[str, str], components: tuple[str, ...]) -> str:
    if not previous_versions:
        return "install"
    target = version_tuple(version)
    values = [version_tuple(value) for value in previous_versions.values()]
    if len(previous_versions) == len(components) and all(value == target for value in values):
        return "repair"
    if any(target < value for value in values):
        return "downgrade"
    return "update"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or update StackMarshal from verified GitHub Release assets")
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-base-url", required=True)
    parser.add_argument("--repository-url", default=REPOSITORY_URL)
    parser.add_argument("--install-root", type=Path, default=default_install_root())
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-downgrade", action="store_true")
    parser.add_argument("--cli-only", action="store_true")
    parser.add_argument("--skill-only", action="store_true")
    parser.add_argument("--no-path", action="store_true")
    args = parser.parse_args(argv)
    install_lock: InstallerLock | None = None

    try:
        if args.cli_only and args.skill_only:
            raise InstallError("--cli-only and --skill-only cannot be combined")
        if sys.version_info < MIN_PYTHON:
            raise InstallError("StackMarshal requires Python 3.11 or newer")
        version = normalize_version(args.version)
        install_root = args.install_root.expanduser().resolve()
        codex_home = args.codex_home.expanduser().resolve()
        validate_managed_roots(install_root, codex_home)
        install_root.mkdir(parents=True, exist_ok=True)
        install_lock = acquire_installer_lock(install_root / ".install.lock")
        state_path = install_root / "install-state.json"
        previous = load_state(state_path)
        components = targeted_components(cli_only=args.cli_only, skill_only=args.skill_only)
        previous_versions = installed_component_versions(previous, components)
        target_version = version_tuple(version)
        newer_components = {
            component: installed
            for component, installed in previous_versions.items()
            if target_version < version_tuple(installed)
        }
        if newer_components and not args.allow_downgrade:
            details = ", ".join(f"{component}={installed}" for component, installed in sorted(newer_components.items()))
            raise InstallError(
                f"Refusing to downgrade {details} to {version}; pass --allow-downgrade explicitly"
            )
        action = classify_install_action(version, previous_versions, components)

        staging_root = install_root / ".staging" / uuid.uuid4().hex
        downloads = staging_root / "downloads"
        payload = staging_root / "payload"
        downloads.mkdir(parents=True)
        payload.mkdir(parents=True)
        release_base_url = args.release_base_url.rstrip("/")
        checksum_path = downloads / "SHA256SUMS"
        download(f"{release_base_url}/SHA256SUMS", checksum_path)
        checksums = parse_checksums(checksum_path.read_text(encoding="utf-8"))
        wheel_name = f"stackmarshal-{version}-py3-none-any.whl"
        skill_name = f"stackmarshal-skill-v{version}.zip"
        requested_assets: list[str] = []
        if not args.skill_only:
            requested_assets.append(wheel_name)
        if not args.cli_only:
            requested_assets.append(skill_name)
        asset_hashes: dict[str, str] = {}
        for name in requested_assets:
            destination = downloads / name
            download(f"{release_base_url}/{name}", destination)
            asset_hashes[name] = verify_checksum(destination, checksums)

        new_state = dict(previous)
        version_dir = install_root / "versions" / f"v{version}"
        bin_dir = install_root / "bin"
        path_note: str | None = None
        path_changed = False
        user_skill_backup: Path | None = None
        cli_swap: DirectorySwap | None = None
        skill_swap: DirectorySwap | None = None
        launcher_path: Path | None = None
        launcher_snapshot: FileSnapshot | None = None
        state_snapshot = snapshot_file(state_path)
        prepared_skill: Path | None = None

        staged_version: Path | None = None
        if not args.skill_only:
            staged_version = payload / f"v{version}"
            staged_venv = staged_version / "venv"
            create_venv(Path(sys.executable).resolve(), staged_venv, downloads / wheel_name, version)

        skill_hash: str | None = None
        skill_destination: Path | None = None
        if not args.cli_only:
            staged_skill = safe_extract_skill_zip(downloads / skill_name, payload / "skill")
            skill_destination = codex_home / "skills" / "stackmarshal"
            previous_skill = previous.get("skill") if isinstance(previous.get("skill"), dict) else {}
            previous_hash = previous_skill.get("tree_sha256") if isinstance(previous_skill, dict) else None
            skill_hash, user_skill_backup, prepared_skill = prepare_skill_swap(
                staged_skill,
                skill_destination,
                install_root=install_root,
                previous_hash=previous_hash if isinstance(previous_hash, str) else None,
                assume_yes=args.yes,
                force=args.force,
            )

        try:
            if staged_version is not None:
                cli_swap = apply_directory_swap(staged_version, version_dir, install_root)
                launcher_name, launcher = launcher_text(version)
                launcher_path = bin_dir / launcher_name
                launcher_snapshot = snapshot_file(launcher_path)
                atomic_write_text(launcher_path, launcher, executable=os.name != "nt")
                new_state["cli"] = {
                    "version": version,
                    "launcher": str(launcher_path),
                    "version_dir": str(version_dir),
                    "wheel_sha256": asset_hashes[wheel_name],
                    "python": {
                        "source_executable": str(Path(sys.executable).resolve()),
                        "version": platform.python_version(),
                    },
                    "path_updated": False,
                }

            if prepared_skill is not None and skill_destination is not None and skill_hash is not None:
                skill_swap = apply_directory_swap(prepared_skill, skill_destination, skill_destination.parent)
                new_state["skill"] = {
                    "version": version,
                    "path": str(skill_destination),
                    "tree_sha256": skill_hash,
                    "archive_sha256": asset_hashes[skill_name],
                }

            new_state.update(
                {
                    "schema_version": 1,
                    "version": version,
                    "tag": f"v{version}",
                    "installation_mode": "full" if len(components) == 2 else f"{components[0]}-only",
                    "repository": args.repository_url,
                    "release_base_url": release_base_url,
                    "installed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "action": action,
                }
            )

            doctor: dict[str, Any] = {
                "state": False,
                "version": version,
                "cli": None,
                "skill": None,
            }
            if not args.skill_only:
                python = venv_python(version_dir / "venv")
                doctor["cli"] = (
                    run_checked([str(python), "-I", "-m", "stackmarshal.cli", "--version"]).stdout.strip()
                    == version
                )
            if not args.cli_only and skill_destination is not None and skill_hash is not None:
                doctor["skill"] = (
                    (skill_destination / "SKILL.md").is_file() and tree_hash(skill_destination) == skill_hash
                )
            if doctor["cli"] is False or doctor["skill"] is False:
                raise InstallError("Post-install doctor check failed")
            write_state(state_path, new_state)
            doctor["state"] = state_path.is_file()
            if not doctor["state"]:
                raise InstallError("Installer state was not persisted")
        except Exception:
            try:
                restore_file(state_path, state_snapshot, install_root)
                if launcher_path is not None and launcher_snapshot is not None:
                    restore_file(launcher_path, launcher_snapshot, bin_dir)
                if skill_swap is not None:
                    skill_swap.rollback()
                if cli_swap is not None:
                    cli_swap.rollback()
                if prepared_skill is not None and (prepared_skill.exists() or prepared_skill.is_symlink()):
                    safe_remove(prepared_skill, prepared_skill.parent)
                if user_skill_backup is not None and user_skill_backup.exists():
                    safe_remove(user_skill_backup, install_root)
            except Exception as rollback_error:
                raise InstallError(f"Installation failed and rollback was incomplete: {rollback_error}") from rollback_error
            raise
        else:
            cleanup_warnings: list[str] = []
            for swap in (skill_swap, cli_swap):
                if swap is None:
                    continue
                try:
                    swap.finalize()
                except Exception as cleanup_error:
                    cleanup_warnings.append(str(cleanup_error))
            if not args.skill_only:
                try:
                    remove_old_versions(install_root / "versions", version_dir, install_root)
                except Exception as cleanup_error:
                    cleanup_warnings.append(str(cleanup_error))
                try:
                    path_changed, path_note = install_path(
                        bin_dir, assume_yes=args.yes, no_path=args.no_path
                    )
                except Exception as path_error:
                    path_note = f"PATH was not changed: {path_error}. Add {bin_dir} manually."
                cli_state = new_state.get("cli")
                if isinstance(cli_state, dict):
                    cli_state["path_updated"] = path_changed
                    cli_state["path_note"] = path_note
                    try:
                        write_state(state_path, new_state)
                    except Exception as state_error:
                        cleanup_warnings.append(f"Could not persist PATH status: {state_error}")
            if cleanup_warnings:
                path_note = "; ".join(filter(None, [path_note, *cleanup_warnings]))

        print(json.dumps({
            "installed": True,
            "action": action,
            "version": version,
            "install_root": str(install_root),
            "codex_home": str(codex_home),
            "doctor": doctor,
            "path_note": path_note,
            "skill_backup": str(user_skill_backup) if user_skill_backup else None,
            "restart_codex": not args.cli_only,
        }, indent=2))
        return 0
    except InstallError as exc:
        print(json.dumps({"installed": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            json.dumps({"installed": False, "error": f"Unexpected installer failure: {exc}"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    finally:
        try:
            if "staging_root" in locals() and staging_root.exists():
                safe_remove(staging_root, install_root)
            staging_parent = install_root / ".staging" if "install_root" in locals() else None
            if staging_parent is not None and staging_parent.exists() and not any(staging_parent.iterdir()):
                staging_parent.rmdir()
        except Exception as cleanup_error:
            print(f"Warning: installer cleanup failed: {cleanup_error}", file=sys.stderr)
        finally:
            if install_lock is not None:
                try:
                    install_lock.release()
                except Exception as lock_error:
                    print(f"Warning: installer lock release failed: {lock_error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
