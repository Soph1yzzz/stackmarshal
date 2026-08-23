from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid
from typing import Any

from .config import Config
from .constants import Mode, Phase, SCHEMA_VERSION, Status
from .models import BudgetState, Invocation, ProjectInfo, RunState

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")


_ALLOWED_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.INVOCATION_CHECK: {Phase.INTENT_NORMALIZATION, Phase.STOPPED},
    Phase.INTENT_NORMALIZATION: {Phase.ENVIRONMENT_AUDIT, Phase.STOPPED},
    Phase.ENVIRONMENT_AUDIT: {Phase.RESEARCH_GATE, Phase.STOPPED},
    Phase.RESEARCH_GATE: {Phase.LANDSCAPE_RESEARCH, Phase.CAPABILITY_MAPPING, Phase.STOPPED},
    Phase.LANDSCAPE_RESEARCH: {Phase.CAPABILITY_MAPPING, Phase.STOPPED},
    Phase.CAPABILITY_MAPPING: {Phase.CAPABILITY_DISCOVERY, Phase.ARCHITECTURE_FREEZE, Phase.STOPPED},
    Phase.CAPABILITY_DISCOVERY: {Phase.TRUST_EVALUATION, Phase.STOPPED},
    Phase.TRUST_EVALUATION: {Phase.ISOLATED_POC, Phase.ARCHITECTURE_FREEZE, Phase.STOPPED},
    Phase.ISOLATED_POC: {Phase.ARCHITECTURE_FREEZE, Phase.STOPPED},
    Phase.ARCHITECTURE_FREEZE: {Phase.TASK_GRAPH, Phase.LANDSCAPE_RESEARCH, Phase.STOPPED},
    Phase.TASK_GRAPH: {Phase.IMPLEMENTATION, Phase.COMPLETE, Phase.STOPPED},
    Phase.IMPLEMENTATION: {Phase.VERIFICATION, Phase.REPLAN, Phase.STOPPED},
    Phase.VERIFICATION: {Phase.COMPLETE, Phase.REPLAN, Phase.CHECKPOINTING},
    Phase.REPLAN: {Phase.IMPLEMENTATION, Phase.LANDSCAPE_RESEARCH, Phase.CHECKPOINTING},
    Phase.CHECKPOINTING: {Phase.STOPPED},
    Phase.COMPLETE: set(),
    Phase.STOPPED: set(),
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _run_git_bytes(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"Git worktree fingerprint failed: {' '.join(args)}") from exc
    return result.stdout


def _tree_fingerprint(root: Path, ignored_dirs: set[str]) -> str:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"Workspace fingerprint root is not a directory: {root}")
    digest = hashlib.sha256()
    pending = [resolved]
    visited_dirs = {resolved}
    while pending:
        directory = pending.pop()
        children = sorted(directory.iterdir(), key=lambda item: item.name.casefold(), reverse=True)
        for candidate in children:
            relative = candidate.relative_to(resolved)
            if any(part in ignored_dirs for part in relative.parts):
                continue
            digest.update(relative.as_posix().encode("utf-8", errors="surrogateescape"))
            digest.update(b"\0")
            if candidate.is_symlink():
                digest.update(b"symlink\0")
                digest.update(str(candidate.readlink()).encode("utf-8", errors="surrogateescape"))
                digest.update(b"\0")
                continue
            try:
                resolved_candidate = candidate.resolve(strict=True)
            except OSError as exc:
                raise ValueError(f"Workspace entry changed during fingerprint: {relative.as_posix()}") from exc
            if resolved_candidate != resolved and resolved not in resolved_candidate.parents:
                raise ValueError(f"Workspace entry escapes during fingerprint: {relative.as_posix()}")
            if candidate.is_file():
                digest.update(b"file\0")
                with candidate.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            elif candidate.is_dir():
                if resolved_candidate in visited_dirs:
                    raise ValueError(f"Workspace directory alias or cycle during fingerprint: {relative.as_posix()}")
                visited_dirs.add(resolved_candidate)
                digest.update(b"dir\0")
                pending.append(candidate)
            else:
                raise ValueError(f"Workspace contains unsupported filesystem entry: {relative.as_posix()}")
            digest.update(b"\0")
    return digest.hexdigest()


def workspace_fingerprint(root: Path) -> str:
    """Hash source workspace contents while excluding VCS/runtime/build noise.

    This fingerprint exists to prove that implementation work happened between
    recorded phase boundaries, including before a new repository has a first commit.
    """

    return _tree_fingerprint(
        root,
        {
            ".git",
            ".stackmarshal",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "build",
            "dist",
            "node_modules",
        },
    )


def terminal_workspace_fingerprint(root: Path) -> str:
    """Hash terminal deliverable content, including build/dist/release artifacts."""

    return _tree_fingerprint(
        root,
        {
            ".git",
            ".stackmarshal",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
        },
    )


def terminal_repository_snapshot(root: Path) -> dict[str, Any]:
    """Capture final repository/workspace evidence immediately before COMPLETE."""
    head = _run_git(root, "rev-parse", "HEAD")
    toplevel = _run_git(root, "rev-parse", "--show-toplevel")
    status = _run_git(root, "status", "--porcelain")
    entries = [] if status is None or not status else status.splitlines()
    dirty_paths: list[str] = []
    for entry in entries:
        path = entry[3:] if len(entry) > 3 else entry
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty_paths.append(path)
    return {
        "timestamp": now_iso(),
        "git_head": head,
        "git_toplevel": toplevel,
        "git_dirty": bool(entries),
        "git_dirty_paths": dirty_paths,
        "git_status_porcelain": entries,
        "workspace_fingerprint": terminal_workspace_fingerprint(root),
    }


def worktree_fingerprint(root: Path) -> str | None:
    """Hash tracked diffs plus untracked file contents for checkpoint resume safety."""

    resolved = root.resolve()
    top_level = _run_git(resolved, "rev-parse", "--show-toplevel")
    if not top_level or Path(top_level).resolve() != resolved:
        return None
    if _run_git(resolved, "rev-parse", "HEAD") is None:
        return workspace_fingerprint(resolved)
    digest = hashlib.sha256()
    for label, args in (
        (b"tracked\0", ("diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--")),
        (b"staged\0", ("diff", "--no-ext-diff", "--no-textconv", "--binary", "--cached", "HEAD", "--")),
    ):
        digest.update(label)
        digest.update(_run_git_bytes(resolved, *args))
    untracked = _run_git_bytes(
        resolved, "ls-files", "--others", "--exclude-standard", "-z"
    )
    for raw_name in sorted(item for item in untracked.split(b"\0") if item):
        relative_text = raw_name.decode("utf-8", errors="surrogateescape")
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe untracked path from Git: {relative_text!r}")
        candidate = resolved / relative
        digest.update(b"untracked\0")
        digest.update(raw_name)
        digest.update(b"\0")
        if candidate.is_symlink():
            digest.update(b"symlink\0")
            digest.update(str(candidate.readlink()).encode("utf-8", errors="surrogateescape"))
        elif candidate.is_file():
            try:
                resolved_candidate = candidate.resolve(strict=True)
            except OSError as exc:
                raise ValueError(f"Untracked worktree path changed during fingerprint: {relative_text}") from exc
            if resolved_candidate != resolved and resolved not in resolved_candidate.parents:
                raise ValueError(f"Untracked worktree path escapes workspace: {relative_text}")
            digest.update(b"file\0")
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            raise ValueError(f"Untracked worktree path changed during fingerprint: {relative_text}")
        digest.update(b"\0")
    return digest.hexdigest()


def project_info(root: Path) -> ProjectInfo:
    resolved = root.resolve()
    discovered_top_level = _run_git(resolved, "rev-parse", "--show-toplevel")
    top_level = Path(discovered_top_level).resolve() if discovered_top_level else None
    repository_owned = top_level == resolved
    if repository_owned:
        head = _run_git(resolved, "rev-parse", "HEAD")
        status = _run_git(resolved, "status", "--porcelain")
        roots = _run_git(resolved, "rev-list", "--max-parents=0", "HEAD")
        remote = _run_git(resolved, "config", "--get", "remote.origin.url")
        lineage = sorted(roots.splitlines()) if roots else []
    else:
        # An ancestor repository is context, not ownership. Treat this workspace
        # as repository-free until it is explicitly bootstrapped itself.
        head = None
        status = None
        remote = None
        lineage = []
        top_level = None
    identity_seed = json.dumps(
        {
            "root": str(resolved),
            "git_toplevel": str(top_level) if top_level else None,
            "root_commits": lineage,
            "remote_origin": remote or None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    identity = hashlib.sha256(identity_seed.encode()).hexdigest()
    return ProjectInfo(
        root=str(resolved),
        git_head=head,
        identity_hash=identity,
        dirty=bool(status),
        git_toplevel=str(top_level) if top_level else None,
        repository_owned=repository_owned,
        repository_lineage=lineage,
    )


def refresh_project_info(state: RunState, root: Path) -> dict[str, Any] | None:
    """Refresh mutable Git facts and permit only explicit bootstrap lineage changes."""

    current = project_info(root)
    previous = state.project
    if current.identity_hash == previous.identity_hash:
        state.project = current
        state.updated_at = now_iso()
        return None

    bootstrap = previous.git_toplevel is None and current.repository_owned
    first_commit = (
        previous.repository_owned
        and current.repository_owned
        and previous.git_toplevel == current.git_toplevel
        and not previous.repository_lineage
        and bool(current.repository_lineage)
    )
    if not (bootstrap or first_commit):
        raise ValueError("Project identity changed outside an allowed repository bootstrap")

    event = {
        "reason": "workspace_repository_bootstrap" if bootstrap else "repository_first_commit",
        "from_identity": previous.identity_hash,
        "to_identity": current.identity_hash,
        "git_toplevel": current.git_toplevel,
        "repository_lineage": current.repository_lineage,
    }
    state.project = current
    state.updated_at = now_iso()
    return event


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"Invalid StackMarshal run id: {run_id!r}")
    return run_id


def new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return validate_run_id(f"{stamp}-{uuid.uuid4().hex[:8]}")


def create_run(root: Path, invocation: str, mode: Mode, config: Config) -> RunState:
    timestamp = now_iso()
    return RunState(
        schema_version=SCHEMA_VERSION,
        run_id=new_run_id(),
        project=project_info(root),
        invocation=Invocation(explicit=True, raw_text=invocation),
        mode=mode,
        budget=BudgetState(config.budget_profile, dict(config.limits), {}),
        progress={"live_contract_version": 1},
        created_at=timestamp,
        updated_at=timestamp,
    )


def transition(state: RunState, target: Phase) -> RunState:
    if state.status is not Status.RUNNING:
        raise ValueError(f"Cannot transition terminal run: {state.status}")
    allowed = _ALLOWED_TRANSITIONS[state.phase]
    if target not in allowed:
        raise ValueError(f"Invalid transition: {state.phase} -> {target}")
    if state.phase.value not in state.completed_phases:
        state.completed_phases.append(state.phase.value)
    state.phase = target
    state.updated_at = now_iso()
    if target is Phase.COMPLETE:
        state.status = Status.COMPLETE
    return state


def stop(state: RunState, status: Status, reason: str, details: dict[str, Any] | None = None) -> RunState:
    if status in {Status.RUNNING, Status.COMPLETE}:
        raise ValueError("stop() requires a non-complete terminal status")
    state.status = status
    state.phase = Phase.CHECKPOINTING
    state.stop_reason = {"code": status.value, "reason": reason, "details": details or {}}
    state.updated_at = now_iso()
    return state


def save_state(state: RunState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_state(path: Path) -> RunState:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {raw.get('schema_version')}")
    validate_run_id(str(raw.get("run_id", "")))
    return RunState.from_dict(raw)


def append_event(path: Path, event_type: str, phase: Phase, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = 1
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            seq = sum(1 for _ in handle) + 1
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    event = {
        "seq": seq,
        "timestamp": now_iso(),
        "event_type": event_type,
        "phase": phase.value,
        "payload_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "payload": payload,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def validate_invocation(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    if "$stackmarshal" in normalized:
        return True
    if "stackmarshal" not in normalized:
        return False
    anti_patterns = (
        r"stackmarshal\s*(とは|って何|について|に似た)",
        r"stackmarshal.{0,24}(readme|表記|名前).{0,16}(直|修正|編集)",
        r"(what is|explain|compare).{0,24}stackmarshal",
    )
    if any(re.search(pattern, normalized) for pattern in anti_patterns):
        return False
    use_markers = (
        "を使", "で実装", "で作", "で調べ", "で準備", "で続", "use stackmarshal",
        "with stackmarshal", "使用 stackmarshal", "用 stackmarshal", "stackmarshal로",
        "utilise stackmarshal", "utilize stackmarshal",
    )
    return any(marker in normalized for marker in use_markers)


def infer_mode(text: str) -> Mode:
    normalized = text.casefold()
    if any(token in normalized for token in ("resume", "続きから", "再開", "continue from")):
        return Mode.RESUME
    if any(token in normalized for token in ("prepare", "準備", "計画まで", "plan only")):
        return Mode.PREPARE
    if any(token in normalized for token in ("research", "調べ", "比較", "investigate")) and not any(
        token in normalized for token in ("実装", "作って", "build", "implement", "实现")
    ):
        return Mode.RESEARCH
    return Mode.BUILD
