from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
from threading import Thread
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def _serve(directory: Path) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(directory)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _load_installer() -> object:
    path = ROOT / "scripts" / "installer.py"
    spec = importlib.util.spec_from_file_location("stackmarshal_installer", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _zip_entry(archive: zipfile.ZipFile, name: str, payload: bytes, mode: int = 0o100644) -> None:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    archive.writestr(info, payload)


def test_version_and_checksum_parsing_is_strict() -> None:
    installer = _load_installer()
    assert installer.normalize_version("v1.2.3") == "1.2.3"  # type: ignore[attr-defined]
    assert installer.version_tuple("1.10.0") > installer.version_tuple("1.9.9")  # type: ignore[attr-defined]
    checksums = installer.parse_checksums("a" * 64 + "  artifact.whl\n")  # type: ignore[attr-defined]
    assert checksums == {"artifact.whl": "a" * 64}

    for malformed in (
        "a" * 64 + " *artifact.whl\n",
        "a" * 64 + "  ../artifact.whl\n",
        "a" * 63 + "  artifact.whl\n",
        "a" * 64 + "  artifact.whl\n" + "b" * 64 + "  artifact.whl\n",
    ):
        with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
            installer.parse_checksums(malformed)  # type: ignore[attr-defined]


def test_skill_zip_extracts_only_regular_contained_files(tmp_path: Path) -> None:
    installer = _load_installer()
    archive_path = tmp_path / "skill.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        _zip_entry(archive, "stackmarshal/SKILL.md", b"---\nname: stackmarshal\n---\n")
        _zip_entry(archive, "stackmarshal/scripts/tool.py", b"print('ok')\n")

    extracted = installer.safe_extract_skill_zip(archive_path, tmp_path / "output")  # type: ignore[attr-defined]
    assert (extracted / "SKILL.md").is_file()
    assert (extracted / "scripts" / "tool.py").read_bytes() == b"print('ok')\n"


@pytest.mark.parametrize(
    "name,mode",
    [
        ("../outside.txt", 0o100644),
        ("stackmarshal/../../outside.txt", 0o100644),
        ("stackmarshal/link", stat.S_IFLNK | 0o777),
    ],
)
def test_skill_zip_rejects_unsafe_entries(tmp_path: Path, name: str, mode: int) -> None:
    installer = _load_installer()
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        _zip_entry(archive, "stackmarshal/SKILL.md", b"skill")
        _zip_entry(archive, name, b"payload", mode)
    with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
        installer.safe_extract_skill_zip(archive_path, tmp_path / "output")  # type: ignore[attr-defined]


def test_tree_hash_rejects_symlinks_when_supported(tmp_path: Path) -> None:
    installer = _load_installer()
    root = tmp_path / "tree"
    root.mkdir()
    (root / "file.txt").write_text("ok", encoding="utf-8")
    target = tmp_path / "target.txt"
    target.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")
    with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
        installer.tree_hash(root)  # type: ignore[attr-defined]

    managed = tmp_path / "managed"
    managed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    redirected = managed / ".staging"
    redirected.symlink_to(outside, target_is_directory=True)
    with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
        installer.ensure_managed_directory(redirected / "run" / "downloads", managed)  # type: ignore[attr-defined]
    assert not (outside / "run").exists()

    root_link = tmp_path / "install-link"
    root_link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
        installer.ensure_root_directory(root_link, "install root")  # type: ignore[attr-defined]


def test_directory_swap_can_rollback_and_finalize(tmp_path: Path) -> None:
    installer = _load_installer()
    root = tmp_path / "managed"
    root.mkdir()
    destination = root / "current"
    destination.mkdir()
    (destination / "value.txt").write_text("old", encoding="utf-8")
    staged = root / "staged"
    staged.mkdir()
    (staged / "value.txt").write_text("new", encoding="utf-8")

    swap = installer.apply_directory_swap(staged, destination, root)  # type: ignore[attr-defined]
    assert (destination / "value.txt").read_text(encoding="utf-8") == "new"
    swap.rollback()
    assert (destination / "value.txt").read_text(encoding="utf-8") == "old"

    staged_again = root / "staged-again"
    staged_again.mkdir()
    (staged_again / "value.txt").write_text("final", encoding="utf-8")
    swap = installer.apply_directory_swap(staged_again, destination, root)  # type: ignore[attr-defined]
    swap.finalize()
    assert (destination / "value.txt").read_text(encoding="utf-8") == "final"
    assert not any(path.name.startswith(".current.old-") for path in root.iterdir())


def test_download_url_policy_allows_https_and_loopback_only() -> None:
    installer = _load_installer()
    assert installer.validate_download_url("https://example.com/file").scheme == "https"  # type: ignore[attr-defined]
    assert installer.validate_download_url("http://127.0.0.1:8765/file").hostname == "127.0.0.1"  # type: ignore[attr-defined]
    for url in ("http://example.com/file", "file:///tmp/file", "https://user:pass@example.com/file"):
        with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
            installer.validate_download_url(url)  # type: ignore[attr-defined]


def test_managed_roots_reject_filesystem_root_and_overlap(tmp_path: Path) -> None:
    installer = _load_installer()
    with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
        installer.validate_managed_roots(Path(tmp_path.anchor), tmp_path / "codex")  # type: ignore[attr-defined]
    with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
        installer.validate_managed_roots(tmp_path / "app", tmp_path / "app" / "codex")  # type: ignore[attr-defined]


def test_installer_lock_rejects_parallel_use(tmp_path: Path) -> None:
    installer = _load_installer()
    lock_path = tmp_path / "app" / ".install.lock"
    lock_path.parent.mkdir()
    first = installer.acquire_installer_lock(lock_path)  # type: ignore[attr-defined]
    try:
        with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
            installer.acquire_installer_lock(lock_path)  # type: ignore[attr-defined]
    finally:
        first.release()
    second = installer.acquire_installer_lock(lock_path)  # type: ignore[attr-defined]
    second.release()


def test_skill_zip_rejects_reserved_and_case_colliding_names(tmp_path: Path) -> None:
    installer = _load_installer()
    reserved = tmp_path / "reserved.zip"
    with zipfile.ZipFile(reserved, "w") as archive:
        _zip_entry(archive, "stackmarshal/SKILL.md", b"skill")
        _zip_entry(archive, "stackmarshal/NUL.txt", b"payload")
    with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
        installer.safe_extract_skill_zip(reserved, tmp_path / "reserved-output")  # type: ignore[attr-defined]

    collision = tmp_path / "collision.zip"
    with zipfile.ZipFile(collision, "w") as archive:
        _zip_entry(archive, "stackmarshal/SKILL.md", b"skill")
        _zip_entry(archive, "stackmarshal/Readme.txt", b"one")
        _zip_entry(archive, "stackmarshal/README.TXT", b"two")
    with pytest.raises(installer.InstallError):  # type: ignore[attr-defined]
        installer.safe_extract_skill_zip(collision, tmp_path / "collision-output")  # type: ignore[attr-defined]


def test_unix_profile_block_quotes_the_managed_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installer = _load_installer()
    profile = tmp_path / ".profile"
    profile.write_text("export EXISTING=1\n", encoding="utf-8")
    monkeypatch.setattr(installer, "choose_unix_profile", lambda: profile)
    managed_bin = tmp_path / "bin with spaces;$(touch injected)"
    assert installer.add_unix_profile_path(managed_bin) == profile  # type: ignore[attr-defined]
    text = profile.read_text(encoding="utf-8")
    assert "STACKMARSHAL_BIN=" in text
    assert "export PATH=\"$STACKMARSHAL_BIN:$PATH\"" in text
    assert not (tmp_path / "injected").exists()


def test_restart_marker_is_versioned_and_stored_in_codex_home(tmp_path: Path) -> None:
    installer = _load_installer()
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    marker = installer.restart_marker_path(codex_home)  # type: ignore[attr-defined]
    installer.write_restart_marker(marker, "1.1.1")  # type: ignore[attr-defined]
    assert marker.parent == codex_home
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["version"] == "1.1.1"
    assert payload["reason"] == "stackmarshal_skill_installed_or_updated"
    assert payload["created_at"].endswith("+00:00")


def test_checksum_mismatch_fails_closed_and_cleans_staging(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    wheel_name = "stackmarshal-1.1.0-py3-none-any.whl"
    (release / wheel_name).write_bytes(b"not-a-wheel")
    (release / "SHA256SUMS").write_text("0" * 64 + f"  {wheel_name}\n", encoding="utf-8")
    install_root = tmp_path / "app"

    with _serve(release) as base_url:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "installer.py"),
                "--version",
                "1.1.0",
                "--release-base-url",
                base_url,
                "--install-root",
                str(install_root),
                "--codex-home",
                str(tmp_path / "codex"),
                "--cli-only",
                "--yes",
                "--no-path",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

    assert result.returncode == 1
    assert "Checksum mismatch" in result.stderr
    assert not (install_root / "install-state.json").exists()
    assert not (install_root / ".staging").exists()


def test_downgrade_requires_explicit_approval(tmp_path: Path) -> None:
    install_root = tmp_path / "app"
    install_root.mkdir()
    state = install_root / "install-state.json"
    original_state = {
        "version": "9.0.0",
        "cli": {"version": "9.0.0"},
        "skill": {"version": "9.0.0"},
    }
    state.write_text(json.dumps(original_state), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "installer.py"),
            "--version",
            "1.1.0",
            "--release-base-url",
            "http://127.0.0.1:1",
            "--install-root",
            str(install_root),
            "--codex-home",
            str(tmp_path / "codex"),
            "--yes",
            "--no-path",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "Refusing to downgrade" in result.stderr
    assert json.loads(state.read_text(encoding="utf-8")) == original_state
    assert not (install_root / ".staging").exists()


def test_component_specific_action_and_downgrade_classification() -> None:
    installer = _load_installer()
    previous = {
        "cli": {"version": "1.0.0"},
        "skill": {"version": "2.0.0"},
    }
    cli_versions = installer.installed_component_versions(previous, ("cli",))  # type: ignore[attr-defined]
    skill_versions = installer.installed_component_versions(previous, ("skill",))  # type: ignore[attr-defined]
    assert installer.classify_install_action("1.1.0", cli_versions, ("cli",)) == "update"  # type: ignore[attr-defined]
    assert installer.classify_install_action("1.1.0", skill_versions, ("skill",)) == "downgrade"  # type: ignore[attr-defined]
    assert installer.classify_install_action("1.0.0", cli_versions, ("cli",)) == "repair"  # type: ignore[attr-defined]


def test_installer_bootstraps_require_git_and_verify_release_installer() -> None:
    powershell = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    shell = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    for text in (powershell, shell):
        assert "Git was not found" in text
        assert "installer.py" in text
        assert "SHA256SUMS" in text
        assert "allow-downgrade" in text.lower().replace("_", "-")
    assert "winget" in powershell
    assert "Get-FileHash" not in powershell
    assert "Security.Cryptography.SHA256" in powershell
    assert "/dev/tty" in shell
    assert "apt-get" in shell and "brew" in shell
    assert "hmac.compare_digest" in shell
    assert "hashlib.compare_digest" not in shell
    installer = (ROOT / "scripts" / "installer.py").read_text(encoding="utf-8")
    assert "-I -m stackmarshal.cli" in installer
    assert '"--isolated"' in installer
