from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tomllib
import shutil
import subprocess
import sys
import tempfile
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


VERSION = project_version()


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def release_server(directory: Path) -> Iterator[str]:
    handler = partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def run(command: list[str], *, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Installer smoke command failed ({result.returncode}): {command!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def launcher_path(install_root: Path) -> Path:
    return install_root / "bin" / ("stackmarshal.cmd" if os.name == "nt" else "stackmarshal")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test StackMarshal release installation")
    parser.add_argument(
        "--direct-installer",
        action="store_true",
        help="Exercise the shared installer directly when the host cannot spawn the platform bootstrap shell",
    )
    args = parser.parse_args(argv)
    release = ROOT / "release"
    required = [
        release / "SHA256SUMS",
        release / "installer.py",
        release / "install.ps1",
        release / "install.sh",
        release / f"stackmarshal-{VERSION}-py3-none-any.whl",
        release / f"stackmarshal-skill-v{VERSION}.zip",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Release assets are missing: {missing}")

    with tempfile.TemporaryDirectory(prefix="stackmarshal-installer-smoke-") as temporary:
        root = Path(temporary)
        server_root = root / "server"
        release_root = server_root / f"v{VERSION}"
        shutil.copytree(release, release_root)
        install_root = root / "app"
        codex_home = root / "codex"
        with release_server(server_root) as base_url:
            if args.direct_installer:
                result = _run_direct_installer(base_url, install_root, codex_home, release)
            else:
                result = _run_bootstrap(base_url, install_root, codex_home, release)

        if '"installed": true' not in result.stdout:
            raise RuntimeError(f"Installer did not report success:\n{result.stdout}")

        launcher = launcher_path(install_root)
        if not launcher.is_file():
            raise RuntimeError(f"Launcher is missing: {launcher}")
        version = run([str(launcher), "--version"]).stdout.strip()
        if version != VERSION:
            raise RuntimeError(f"Launcher returned {version!r}; expected {VERSION!r}")

        state = json.loads((install_root / "install-state.json").read_text(encoding="utf-8"))
        if state["version"] != VERSION or state["action"] != "install":
            raise RuntimeError(f"Unexpected installer state: {state}")
        if state["cli"]["version"] != VERSION or state["skill"]["version"] != VERSION:
            raise RuntimeError("CLI and Skill versions are not synchronized")
        python_version = tuple(int(part) for part in state["cli"]["python"]["version"].split(".")[:2])
        if python_version < (3, 11):
            raise RuntimeError(f"Installer selected unsupported Python {python_version}")
        if not (codex_home / "skills" / "stackmarshal" / "SKILL.md").is_file():
            raise RuntimeError("Installed Skill is missing")
        restart_marker = codex_home / ".stackmarshal-restart-required.json"
        if not restart_marker.is_file():
            raise RuntimeError("Restart-pending marker is missing")
        marker = json.loads(restart_marker.read_text(encoding="utf-8"))
        if marker.get("version") != VERSION:
            raise RuntimeError(f"Unexpected restart marker: {marker}")
        if (install_root / ".staging").exists():
            raise RuntimeError("Installer staging directory was not cleaned")

    print(
        f"StackMarshal installer smoke passed on {sys.platform} "
        f"using Python {state['cli']['python']['version']}"
    )
    return 0


def _run_direct_installer(
    base_url: str,
    install_root: Path,
    codex_home: Path,
    release: Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
    command = [
        sys.executable,
        str(release / "installer.py"),
        "--version",
        VERSION,
        "--release-base-url",
        f"{base_url}/v{VERSION}",
        "--install-root",
        str(install_root),
        "--codex-home",
        str(codex_home),
        "--yes",
        "--no-path",
    ]
    return run(command, environment=environment)


def _run_bootstrap(base_url: str, install_root: Path, codex_home: Path, release: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "STACKMARSHAL_BOOTSTRAP_URL": f"{base_url}/v{VERSION}/{'install.ps1' if os.name == 'nt' else 'install.sh'}",
            "STACKMARSHAL_VERSION": f"v{VERSION}",
            "STACKMARSHAL_INSTALL_ROOT": str(install_root),
            "STACKMARSHAL_CODEX_HOME": str(codex_home),
            "STACKMARSHAL_RELEASE_BASE_PREFIX": base_url,
            "STACKMARSHAL_ASSUME_YES": "1",
            "STACKMARSHAL_NO_PATH": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "irm $env:STACKMARSHAL_BOOTSTRAP_URL | iex",
        ]
    else:
        command = [
            "bash",
            "-c",
            'curl -fsSL "$STACKMARSHAL_BOOTSTRAP_URL" | bash -s -- '
            '--version "$STACKMARSHAL_VERSION" --yes --no-path '
            '--install-root "$STACKMARSHAL_INSTALL_ROOT" '
            '--codex-home "$STACKMARSHAL_CODEX_HOME" '
            '--release-base-prefix "$STACKMARSHAL_RELEASE_BASE_PREFIX"',
        ]
    return run(command, environment=environment)


if __name__ == "__main__":
    raise SystemExit(main())
