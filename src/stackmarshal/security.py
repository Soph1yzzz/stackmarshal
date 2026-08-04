from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import re

from .constants import CommandClass


@dataclass(frozen=True, slots=True)
class CommandDecision:
    command_class: CommandClass
    approval_required: bool
    reasons: tuple[str, ...]


_APPROVAL_CLASSES = {
    CommandClass.GLOBAL_WRITE,
    CommandClass.NETWORK_WRITE,
    CommandClass.SECRET_ACCESS,
    CommandClass.BILLABLE_ACTION,
    CommandClass.PUBLICATION,
    CommandClass.PRIVILEGED,
}


def classify_command(argv: Iterable[str], project_root: Path | None = None) -> CommandDecision:
    tokens = tuple(str(item) for item in argv)
    joined = " ".join(tokens).casefold()
    reasons: list[str] = []
    command_class = CommandClass.READ_ONLY
    if re.search(r"\b(git push|gh release create|gh repo create|npm publish|twine upload|uv publish)\b", joined):
        command_class = CommandClass.PUBLICATION
        reasons.append("publishes or modifies a public remote")
    elif re.search(r"\b(sudo|runas|choco install|winget install|apt install|brew install)\b", joined):
        command_class = CommandClass.PRIVILEGED
        reasons.append("may require elevated or machine-wide changes")
    elif re.search(r"\b(curl|wget|invoke-webrequest)\b", joined) and re.search(
        r"(?:^|\s)(?:-x\s+post|--request\s+post|--upload-file(?:\s|$)|put(?:\s|$)|delete(?:\s|$))",
        joined,
    ):
        command_class = CommandClass.NETWORK_WRITE
        reasons.append("writes to a network service")
    elif re.search(r"\b(cat|type|read|get-content)\b.*(\.ssh|\.aws|credentials|keychain|secret)", joined):
        command_class = CommandClass.SECRET_ACCESS
        reasons.append("may read secrets or credentials")
    elif re.search(r"\b(pip install --user|npm install -g|cargo install|go install)\b", joined):
        command_class = CommandClass.GLOBAL_WRITE
        reasons.append("installs outside the project")
    elif re.search(r"\b(rm|del|remove-item|git clean|git reset --hard)\b", joined):
        command_class = CommandClass.PROJECT_WRITE
        reasons.append("destructive project write; verify scope and rollback")
    elif re.search(r"\b(write|install|add|remove|mv|cp|git commit)\b", joined):
        command_class = CommandClass.PROJECT_WRITE
        reasons.append("modifies project files")
    return CommandDecision(command_class, command_class in _APPROVAL_CLASSES, tuple(reasons))


def inspect_package_manifest(text: str) -> list[str]:
    findings: list[str] = []
    lowered = text.casefold()
    for hook in ("postinstall", "preinstall", "prepare", "install"):
        if re.search(rf'["\']{hook}["\']\s*:', lowered):
            findings.append(f"install_hook:{hook}")
    if re.search(r"curl\s+[^|]+\|\s*(sh|bash)", lowered):
        findings.append("download_pipe_shell")
    if re.search(r"powershell.+(iex|invoke-expression)", lowered):
        findings.append("powershell_dynamic_execution")
    return sorted(set(findings))


def ensure_within_workspace(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise ValueError(f"Workspace escape rejected: {candidate}")
    return resolved_candidate
