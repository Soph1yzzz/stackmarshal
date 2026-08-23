from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tomllib
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEMVER = r"\d+\.\d+\.\d+"
README_VERSION_PATTERNS = (
    rf"releases/download/v(?P<version>{SEMVER})/install\.(?:ps1|sh)",
    rf"(?:-Version v|--version v)(?P<version>{SEMVER})",
    rf"/tree/v(?P<version>{SEMVER})/skills/stackmarshal",
    rf"doctor --host-skill-version (?P<version>{SEMVER})",
    rf"stackmarshal-skill-v(?P<version>{SEMVER})\.zip",
)


def _safe_regular_file(root: Path, path: Path) -> Path:
    """Resolve a version-contract file without following workspace-escape links."""

    resolved_root = root.resolve(strict=True)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Version-contract path escapes repository root: {path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Version-contract path may not be a symlink: {relative.as_posix()}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Version-contract path is missing: {relative.as_posix()}") from exc
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"Version-contract path escapes repository root: {relative.as_posix()}")
    if not resolved.is_file():
        raise ValueError(f"Version-contract path is not a regular file: {relative.as_posix()}")
    return resolved


def project_version(root: Path = ROOT) -> str:
    path = _safe_regular_file(root, root / "pyproject.toml")
    with path.open("rb") as handle:
        value = tomllib.load(handle)["project"]["version"]
    if not isinstance(value, str) or re.fullmatch(SEMVER, value) is None:
        raise ValueError("[project].version must be a semantic version")
    return value


def _versions(root: Path, path: Path, pattern: str) -> list[str]:
    text = _safe_regular_file(root, path).read_text(encoding="utf-8")
    return [match.group("version") for match in re.finditer(pattern, text, flags=re.MULTILINE)]


def component_versions(root: Path = ROOT) -> dict[str, str]:
    current = project_version(root)
    components: dict[str, tuple[Path, str]] = {
        "core": (
            root / "src" / "stackmarshal" / "constants.py",
            rf'^__version__ = "(?P<version>{SEMVER})"$',
        ),
        "skill": (
            root / "skills" / "stackmarshal" / "SKILL.md",
            rf'^  version: "(?P<version>{SEMVER})"$',
        ),
    }
    resolved = {"project": current}
    for name, (path, pattern) in components.items():
        found = _versions(root, path, pattern)
        if len(found) != 1:
            raise ValueError(f"Expected exactly one {name} version declaration in {path.relative_to(root)}")
        resolved[name] = found[0]
    # The installer smoke deliberately resolves the authority at runtime instead of mirroring a literal.
    resolved["installer_smoke"] = current
    return resolved


def _living_document_versions(root: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in (root / "README.md", root / "README.ja.md"):
        versions: list[str] = []
        for pattern in README_VERSION_PATTERNS:
            versions.extend(_versions(root, path, pattern))
        result[path.name] = versions
    return result


def _skill_command_versions(root: Path) -> list[str]:
    path = root / "skills" / "stackmarshal" / "SKILL.md"
    # Keep the command check explicit because these literals are executed by a stale/new host session.
    text = _safe_regular_file(root, path).read_text(encoding="utf-8")
    versions: list[str] = []
    for command in ("host-ready --version", "doctor --host-skill-version"):
        match = re.search(rf'{re.escape(command)} "(?P<version>{SEMVER})"', text)
        if match is None:
            raise ValueError(f"Missing Skill versioned command: {command}")
        versions.append(match.group("version"))
    return versions


def check_version_contract(root: Path = ROOT) -> dict[str, Any]:
    current = project_version(root)
    components = component_versions(root)
    mismatches: list[str] = []
    for name, version in components.items():
        if version != current:
            mismatches.append(f"{name}={version} expected={current}")

    skill_commands = _skill_command_versions(root)
    for version in skill_commands:
        if version != current:
            mismatches.append(f"skill_command={version} expected={current}")

    living_docs = _living_document_versions(root)
    for name, versions in living_docs.items():
        if not versions:
            mismatches.append(f"{name}=no semantic version found")
            continue
        stale = sorted({version for version in versions if version != current})
        if stale:
            mismatches.append(f"{name}=stale versions {','.join(stale)} expected={current}")

    return {
        "schema_version": "1.0",
        "authority": "pyproject.toml:[project].version",
        "version": current,
        "components": components,
        "skill_command_versions": skill_commands,
        "living_document_versions": living_docs,
        "coherent": not mismatches,
        "errors": mismatches,
    }


def sync_version_mirrors(root: Path = ROOT) -> list[str]:
    """Update only current-version mirrors; historical evidence is intentionally untouched."""
    current = project_version(root)
    changed: list[str] = []
    replacements: dict[Path, list[tuple[str, str]]] = {
        root / "src" / "stackmarshal" / "constants.py": [
            (rf'^__version__ = "{SEMVER}"$', f'__version__ = "{current}"'),
        ],
        root / "skills" / "stackmarshal" / "SKILL.md": [
            (rf'^  version: "{SEMVER}"$', f'  version: "{current}"'),
            (rf'host-ready --version "{SEMVER}"', f'host-ready --version "{current}"'),
            (rf'doctor --host-skill-version "{SEMVER}"', f'doctor --host-skill-version "{current}"'),
        ],
        root / "README.md": [(pattern, "__README_VERSION__") for pattern in README_VERSION_PATTERNS],
        root / "README.ja.md": [(pattern, "__README_VERSION__") for pattern in README_VERSION_PATTERNS],
    }
    safe_paths = {path: _safe_regular_file(root, path) for path in replacements}
    for path, rules in replacements.items():
        safe_path = safe_paths[path]
        before = safe_path.read_text(encoding="utf-8")
        after = before
        for pattern, replacement in rules:
            if replacement == "__README_VERSION__":
                def repl(match: re.Match[str]) -> str:
                    start, end = match.span("version")
                    whole = match.group(0)
                    relative_start = start - match.start()
                    relative_end = end - match.start()
                    return whole[:relative_start] + current + whole[relative_end:]
                after = re.sub(pattern, repl, after, flags=re.MULTILINE)
            else:
                after = re.sub(pattern, replacement, after, flags=re.MULTILINE)
        if after != before:
            safe_path.write_text(after, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(root).as_posix())
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or synchronize StackMarshal release-version mirrors")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Validate version coherence (default)")
    group.add_argument("--sync", action="store_true", help="Update current-version mirrors from pyproject.toml")
    args = parser.parse_args()

    changed: list[str] = []
    if args.sync:
        changed = sync_version_mirrors()
    result = check_version_contract()
    result["changed"] = changed
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["coherent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
