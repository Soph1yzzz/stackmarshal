from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

import stackmarshal.pinning as pinning
from stackmarshal.cli import EXIT_INVALID_STATE, main
from stackmarshal.constants import __version__


def test_pin_version_normalization_is_strict() -> None:
    assert pinning.normalize_version("1.2.3") == "1.2.3"
    assert pinning.normalize_version("v1.2.3") == "1.2.3"
    for invalid in ("latest", "1.2", "01.2.3", "v1.2.3-rc1", "../1.2.3"):
        with pytest.raises(pinning.PinError):
            pinning.normalize_version(invalid)


def test_download_bytes_rejects_unsafe_empty_and_oversized_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, payload: bytes, url: str = "https://github.com/file") -> None:
            self.payload = payload
            self.url = url
            self.offset = 0

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def geturl(self) -> str:
            return self.url

        def read(self, size: int) -> bytes:
            chunk = self.payload[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    monkeypatch.setattr(pinning.urllib.request, "urlopen", lambda request, timeout: Response(b"ok"))
    assert pinning._download_bytes("https://github.com/file", limit=8) == b"ok"

    monkeypatch.setattr(pinning.urllib.request, "urlopen", lambda request, timeout: Response(b""))
    with pytest.raises(pinning.PinError, match="empty"):
        pinning._download_bytes("https://github.com/file", limit=8)

    monkeypatch.setattr(pinning.urllib.request, "urlopen", lambda request, timeout: Response(b"0123456789"))
    with pytest.raises(pinning.PinError, match="exceeds"):
        pinning._download_bytes("https://github.com/file", limit=4)

    with pytest.raises(pinning.PinError, match="Unsafe"):
        pinning._download_bytes("http://example.com/file", limit=8)


def test_checksum_parser_is_strict() -> None:
    digest = "a" * 64
    assert pinning._parse_checksums(f"{digest}  install.sh\n") == {"install.sh": digest}
    for malformed in (
        "",
        f"{digest} *install.sh\n",
        f"{digest}  ../install.sh\n",
        f"{digest}  install.sh\n{digest}  install.sh\n",
    ):
        with pytest.raises(pinning.PinError):
            pinning._parse_checksums(malformed)


def test_resolve_pin_target_requires_published_stable_release(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_download_json(url: str) -> dict[str, object]:
        seen.append(url)
        return {"tag_name": "v1.2.3", "draft": False, "prerelease": False}

    monkeypatch.setattr(pinning, "_download_json", fake_download_json)
    assert pinning.resolve_pin_target("latest") == "1.2.3"
    assert seen[-1].endswith("/releases/latest")
    assert pinning.resolve_pin_target("1.2.3") == "1.2.3"
    assert seen[-1].endswith("/releases/tags/v1.2.3")

    monkeypatch.setattr(
        pinning,
        "_download_json",
        lambda url: {"tag_name": "v1.2.3", "draft": False, "prerelease": True},
    )
    with pytest.raises(pinning.PinError, match="published stable"):
        pinning.resolve_pin_target("latest")


def test_verified_bootstrap_checks_release_sha256(monkeypatch: pytest.MonkeyPatch) -> None:
    script_name = "install.ps1" if os.name == "nt" else "install.sh"
    script = b"echo verified\n"
    checksum = hashlib.sha256(script).hexdigest()

    def fake_download(url: str, *, limit: int) -> bytes:
        del limit
        if url.endswith("/SHA256SUMS"):
            return f"{checksum}  {script_name}\n".encode()
        if url.endswith(f"/{script_name}"):
            return script
        raise AssertionError(url)

    monkeypatch.setattr(pinning, "_download_bytes", fake_download)
    assert pinning._verified_bootstrap("1.2.3") == (script_name, script)

    bad = "0" * 64
    monkeypatch.setattr(
        pinning,
        "_download_bytes",
        lambda url, *, limit: (f"{bad}  {script_name}\n".encode() if url.endswith("SHA256SUMS") else script),
    )
    with pytest.raises(pinning.PinError, match="Checksum mismatch"):
        pinning._verified_bootstrap("1.2.3")


def test_install_pin_delegates_to_verified_platform_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del tmp_path
    script_name = "install.ps1" if os.name == "nt" else "install.sh"
    monkeypatch.setattr(pinning, "resolve_pin_target", lambda requested: "1.2.3")
    monkeypatch.setattr(pinning, "_verified_bootstrap", lambda version: (script_name, b"echo ok\n"))
    monkeypatch.setattr(pinning.shutil, "which", lambda name: f"/fake/{name}")
    commands: list[list[str]] = []

    monkeypatch.setenv("STACKMARSHAL_RELEASE_BASE_PREFIX", "https://evil.example/releases")
    monkeypatch.setenv("STACKMARSHAL_REPOSITORY_URL", "https://evil.example/repo.git")
    environments: list[dict[str, str]] = []

    def fake_run(command: list[str], *, check: bool, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        assert check is False
        commands.append(command)
        environments.append(env)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pinning.subprocess, "run", fake_run)
    assert (
        pinning.install_pin(
            "latest",
            assume_yes=True,
            force=True,
            allow_downgrade=True,
            no_path=True,
        )
        == "1.2.3"
    )
    command = commands[0]
    assert "STACKMARSHAL_RELEASE_BASE_PREFIX" not in environments[0]
    assert "STACKMARSHAL_REPOSITORY_URL" not in environments[0]
    if os.name == "nt":
        assert command[0].endswith("powershell.exe")
        assert command[-4:] == ["-Yes", "-Force", "-AllowDowngrade", "-NoPath"]
        assert "v1.2.3" in command
    else:
        assert command[0].endswith("bash")
        assert command[-4:] == ["--yes", "--force", "--allow-downgrade", "--no-path"]
        assert "v1.2.3" in command


def _managed_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, version: str) -> Path:
    base = tmp_path / "managed-base"
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(base))
        root = base / "StackMarshal"
        launcher = root / "bin" / "stackmarshal.cmd"
        launcher_text = f'"%~dp0..\\versions\\v{version}\\venv\\Scripts\\python.exe" -m stackmarshal.cli %*\r\n'
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(base))
        root = base / "stackmarshal"
        launcher = root / "bin" / "stackmarshal"
        launcher_text = f'exec "$SCRIPT_DIR/../versions/v{version}/venv/bin/python" -m stackmarshal.cli "$@"\n'
    launcher.parent.mkdir(parents=True)
    launcher.write_text(launcher_text, encoding="utf-8")
    if os.name != "nt":
        launcher.chmod(0o755)
    (root / "install-state.json").write_text(
        json.dumps(
            {
                "version": version,
                "tag": f"v{version}",
                "cli": {"version": version, "launcher": str(launcher)},
                "skill": {"version": version},
            }
        ),
        encoding="utf-8",
    )
    return launcher


def test_pin_status_and_version_report_aligned_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    codex_home = tmp_path / "codex"
    skill = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f'---\nmetadata:\n  version: "{__version__}"\n---\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    launcher = _managed_layout(tmp_path, monkeypatch, version=__version__)
    monkeypatch.setenv("PATH", str(launcher.parent))

    assert main(["pin", "status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pinned"
    assert payload["pinned_version"] == __version__

    assert main(["version"]) == 0
    output = capsys.readouterr().out
    assert f"StackMarshal {__version__}" in output
    assert f"Pin: v{__version__}" in output
    assert "Status: OK" in output


def test_pin_command_verifies_installed_components_after_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import stackmarshal.cli as cli

    codex_home = tmp_path / "codex"
    skill = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f'---\nmetadata:\n  version: "{__version__}"\n---\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    launcher = _managed_layout(tmp_path, monkeypatch, version=__version__)
    monkeypatch.setenv("PATH", str(launcher.parent))
    observed: list[str] = []

    def fake_install_pin(target: str, **kwargs: object) -> str:
        observed.append(target)
        assert kwargs == {
            "assume_yes": False,
            "force": False,
            "allow_downgrade": False,
            "no_path": False,
        }
        return __version__

    monkeypatch.setattr(cli, "install_pin", fake_install_pin)
    assert main(["pin", "latest"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert observed == ["latest"]
    assert payload["status"] == "pinned"
    assert payload["version"] == __version__
    assert payload["restart_codex"] is True


def test_shadowed_stale_launcher_warns_without_blocking_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    codex_home = tmp_path / "codex"
    skill = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f'---\nmetadata:\n  version: "{__version__}"\n---\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    launcher = _managed_layout(tmp_path, monkeypatch, version=__version__)
    stale_dir = tmp_path / "stale-bin"
    stale_dir.mkdir()
    stale_name = "stackmarshal.cmd" if os.name == "nt" else "stackmarshal"
    stale_launcher = stale_dir / stale_name
    stale_launcher.write_text(
        '"C:/legacy/versions/v1.0.0/venv/Scripts/python.exe" -m stackmarshal.cli\n'
        if os.name == "nt"
        else 'exec "/legacy/versions/v1.0.0/venv/bin/python" -m stackmarshal.cli "$@"\n',
        encoding="utf-8",
    )
    if os.name != "nt":
        stale_launcher.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join((str(launcher.parent), str(stale_dir))))

    assert main(["doctor", "--host-skill-version", __version__]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["ready"] is True
    assert doctor["version_skew"] is False
    assert doctor["shadowed_versions"] == ["1.0.0"]
    assert "shadowed_stackmarshal_versions" in doctor["warnings"]

    assert main(["pin", "status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pinned"


def test_pin_status_reports_runtime_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stale = "1.1.1" if __version__ != "1.1.1" else "1.0.0"
    codex_home = tmp_path / "codex"
    skill = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f'---\nmetadata:\n  version: "{stale}"\n---\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    launcher = _managed_layout(tmp_path, monkeypatch, version=stale)
    monkeypatch.setenv("PATH", str(launcher.parent))

    assert main(["pin", "status"]) == EXIT_INVALID_STATE
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "drifted"
    assert payload["pinned_version"] == stale

    assert main(["version"]) == EXIT_INVALID_STATE
    assert "Status: DRIFTED" in capsys.readouterr().out
