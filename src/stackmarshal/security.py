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


_SAFE_READ_ONLY_COMMANDS = {
    "cat",
    "dir",
    "find",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "tail",
    "tree",
    "where",
    "which",
}
_SAFE_GIT_SUBCOMMANDS = {
    "diff",
    "grep",
    "log",
    "ls-files",
    "rev-list",
    "rev-parse",
    "show",
    "status",
}
_SAFE_GIT_PROJECT_WRITE_SUBCOMMANDS = {
    "add",
    "commit",
    "init",
}
_GIT_UNSAFE_READ_OPTIONS = {
    "--ext-diff",
    "--textconv",
    "--no-index",
    "--open-files-in-pager",
    "--output",
}
_SHELL_META = re.compile(r"(?:^|\s)(?:&&|\|\||[;`]|\$\(|>+|<+)(?:\s|$)")


def _program(tokens: tuple[str, ...]) -> str:
    if not tokens:
        return ""
    return Path(tokens[0].strip('"\'')).name.casefold()


def _has_option(tokens: tuple[str, ...], *names: str) -> bool:
    lowered = {token.casefold() for token in tokens}
    return any(name.casefold() in lowered for name in names)


def _git_read_option_requires_approval(tokens: tuple[str, ...]) -> str | None:
    """Return the unsafe Git option that can cross a read-only trust boundary."""

    for raw in tokens:
        token = raw.casefold()
        name = token.split("=", 1)[0]
        if name in _GIT_UNSAFE_READ_OPTIONS:
            return raw
    return None


def classify_command(argv: Iterable[str], project_root: Path | None = None) -> CommandDecision:
    """Classify a command and fail closed when its effects are not proven read-only.

    `project_root` is reserved for host-specific containment checks. Classification alone never
    treats an unknown executable or subcommand as automatically safe.
    """

    del project_root
    tokens = tuple(str(item) for item in argv)
    joined = " ".join(tokens).casefold().strip()
    program = _program(tokens)

    if not tokens:
        return CommandDecision(CommandClass.READ_ONLY, True, ("empty command; fail closed",))
    if _SHELL_META.search(joined):
        return CommandDecision(
            CommandClass.PRIVILEGED,
            True,
            ("compound shell syntax can hide additional effects; fail closed",),
        )

    if re.search(
        r"\b(git\s+push|gh\s+(?:repo|release)\s+(?:create|delete|rename|archive|upload)|"
        r"gh\s+pr\s+merge|npm\s+(?:publish|unpublish)|twine\s+upload|uv\s+publish|"
        r"cargo\s+publish|docker\s+push)\b",
        joined,
    ):
        return CommandDecision(
            CommandClass.PUBLICATION,
            True,
            ("publishes or modifies a public remote",),
        )

    if re.search(r"\b(sudo|runas|pkexec|doas)\b", joined) or re.search(
        r"\b(choco|winget|apt|apt-get|dnf|yum|brew)\s+(?:install|remove|upgrade|uninstall)\b",
        joined,
    ):
        return CommandDecision(
            CommandClass.PRIVILEGED,
            True,
            ("may require elevated or machine-wide changes",),
        )

    if re.search(
        r"\b(terraform\s+(?:apply|destroy|import)|pulumi\s+(?:up|destroy)|"
        r"(?:aws|gcloud|az)\b.*\b(?:create|deploy|delete|start|run|update)|"
        r"(?:vercel|fly|flyctl|railway|heroku)\s+(?:deploy|up|create|destroy))\b",
        joined,
    ):
        return CommandDecision(
            CommandClass.BILLABLE_ACTION,
            True,
            ("may create, deploy, or consume billable external resources",),
        )

    if re.search(
        r"\b(cat|type|read|get-content|printenv|env|head|tail|grep|rg|find)\b.*"
        r"(\.env(?:\b|\.)|\.ssh|\.aws|\.azure|\.netrc|\.npmrc|\.pypirc|"
        r"/etc/shadow|id_rsa|id_ed25519|credentials|kubeconfig|"
        r"application_default_credentials|docker[/\\\\]config\.json|keychain|"
        r"secret|token|password|private[_-]?key)",
        joined,
    ):
        return CommandDecision(
            CommandClass.SECRET_ACCESS,
            True,
            ("may read secrets or credentials",),
        )

    curl_write = program in {"curl", "curl.exe"} and (
        _has_option(
            tokens,
            "-d",
            "--data",
            "--data-raw",
            "--data-binary",
            "--form",
            "-f",
            "--upload-file",
            "-t",
        )
        or any(token.casefold() in {"post", "put", "patch", "delete"} for token in tokens[1:])
    )
    wget_write = program in {"wget", "wget.exe"} and _has_option(
        tokens, "--post-data", "--post-file", "--method"
    )
    gh_api_write = (
        program in {"gh", "gh.exe"}
        and len(tokens) > 1
        and tokens[1].casefold() == "api"
        and (
            _has_option(tokens, "-f", "--raw-field", "-f", "--field", "--input")
            or any(token.casefold() in {"post", "put", "patch", "delete"} for token in tokens)
        )
    )
    if curl_write or wget_write or gh_api_write or re.search(
        r"\b(invoke-restmethod|invoke-webrequest)\b.*\b(post|put|patch|delete|body|infile)\b",
        joined,
    ):
        return CommandDecision(
            CommandClass.NETWORK_WRITE,
            True,
            ("writes to a network service",),
        )

    if re.search(r"\b(pip\s+install\s+--user|npm\s+install\s+-g|cargo\s+install|go\s+install)\b", joined):
        return CommandDecision(
            CommandClass.GLOBAL_WRITE,
            True,
            ("installs outside the project",),
        )

    if re.search(
        r"\b(rm|del|remove-item|rmdir|git\s+clean|git\s+reset\s+--hard)\b|"
        r"\bfind\b.*(?:-delete|-exec|-execdir)\b",
        joined,
    ):
        return CommandDecision(
            CommandClass.PROJECT_WRITE,
            True,
            ("destructive write requires explicit scope and rollback approval",),
        )

    if program in {"git", "git.exe"} and len(tokens) > 1:
        subcommand = tokens[1].casefold()
        if subcommand.startswith("-"):
            return CommandDecision(
                CommandClass.PROJECT_WRITE,
                True,
                ("Git global options can inject configuration, aliases, pagers, or other effects; fail closed",),
            )
        if subcommand in _SAFE_GIT_SUBCOMMANDS:
            unsafe_option = _git_read_option_requires_approval(tokens[2:])
            if unsafe_option is not None:
                return CommandDecision(
                    CommandClass.PROJECT_WRITE,
                    True,
                    (f"Git read option {unsafe_option!r} can execute helpers, write output, or escape repository reads",),
                )
            return CommandDecision(CommandClass.READ_ONLY, False, ())
        if subcommand in _SAFE_GIT_PROJECT_WRITE_SUBCOMMANDS:
            return CommandDecision(
                CommandClass.PROJECT_WRITE,
                False,
                (f"Git built-in {subcommand!r} modifies only project repository state",),
            )
        return CommandDecision(
            CommandClass.PROJECT_WRITE,
            True,
            (f"unknown or higher-risk Git subcommand {subcommand!r} may be an alias or have destructive effects; fail closed",),
        )

    if program in _SAFE_READ_ONLY_COMMANDS:
        return CommandDecision(CommandClass.READ_ONLY, False, ())

    if program in {"python", "python.exe", "python3", "py", "node", "node.exe"}:
        return CommandDecision(
            CommandClass.PROJECT_WRITE,
            True,
            ("general-purpose interpreter can perform effects beyond project writes; fail closed",),
        )

    if program in {"pytest", "ruff", "mypy"}:
        return CommandDecision(
            CommandClass.PROJECT_WRITE,
            False,
            ("development command may execute project configuration and create local caches",),
        )

    return CommandDecision(
        CommandClass.READ_ONLY,
        True,
        ("unrecognized command effects; fail closed and require approval",),
    )


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
