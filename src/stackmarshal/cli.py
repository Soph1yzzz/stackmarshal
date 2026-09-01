from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from .activity import ActivityBudgetExhausted, completion_activity_errors, record_activity
from .adapters.codex import CodexAdapter
from .budget import check as check_budget
from .checkpoint import create_checkpoint, inspect_checkpoint
from .config import default_config, load_config
from .constants import Mode, Phase, STATE_DIR, Status, __version__
from .failure import fingerprint
from .lock import verify_lock
from .models import ProgressSnapshot
from .progress import evaluate
from .scoring import score_candidate
from .state import (
    append_event,
    create_run,
    infer_mode,
    load_state,
    now_iso,
    refresh_project_info,
    save_state,
    stop,
    terminal_repository_snapshot,
    terminal_workspace_fingerprint,
    transition,
    validate_invocation,
    validate_run_id,
    workspace_fingerprint,
)
from .taskgraph import (
    add_task,
    block_task,
    complete_task,
    completion_errors as task_completion_errors,
    load_task_graph,
    save_task_graph,
    start_task,
)
from .validation import validate_json_file

EXIT_INVALID_INPUT = 2
EXIT_INVALID_STATE = 3
EXIT_BUDGET = 4
EXIT_APPROVAL = 5
EXIT_UNSAFE = 6
EXIT_EXTERNAL = 7
EXIT_CHECKPOINT = 8
EXIT_COMPLETE = 9


def _json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _root(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _assert_workspace_entry(
    root: Path,
    path: Path,
    *,
    expected: str | None = None,
) -> None:
    """Reject symlink/junction escapes before StackMarshal reads or writes workspace state."""

    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise ValueError(f"Workspace root is not a directory: {root}")
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Workspace state path is outside the workspace: {path}") from exc
    if path.is_symlink():
        raise ValueError(f"Workspace state path may not be a symlink: {path.relative_to(root)}")
    if path.exists():
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"Workspace state path cannot be resolved safely: {path.relative_to(root)}") from exc
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise ValueError(f"Workspace state path escapes the workspace: {path.relative_to(root)}")
        if expected == "dir" and not path.is_dir():
            raise ValueError(f"Workspace state directory is not a directory: {path.relative_to(root)}")
        if expected == "file" and not path.is_file():
            raise ValueError(f"Workspace state file is not a regular file: {path.relative_to(root)}")
        return

    ancestor = path.parent
    while not ancestor.exists() and not ancestor.is_symlink() and ancestor != root:
        ancestor = ancestor.parent
    if ancestor.is_symlink():
        raise ValueError(f"Workspace state ancestor may not be a symlink: {ancestor.relative_to(root)}")
    try:
        resolved_ancestor = ancestor.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Workspace state ancestor cannot be resolved safely: {ancestor}") from exc
    if resolved_ancestor != resolved_root and resolved_root not in resolved_ancestor.parents:
        raise ValueError(f"Workspace state ancestor escapes the workspace: {ancestor.relative_to(root)}")


def _paths(root: Path, run_id: str | None = None) -> dict[str, Path]:
    base = root / STATE_DIR
    result = {
        "base": base,
        "config": base / "config.toml",
        "project": base / "project",
        "runs": base / "runs",
    }
    for path, expected in (
        (base, "dir"),
        (result["config"], "file"),
        (result["project"], "dir"),
        (result["runs"], "dir"),
    ):
        _assert_workspace_entry(root, path, expected=expected)
    for name in ("task-graph.json", "task-graph.md", "environment-audit.json", "task-graph.json.tmp"):
        _assert_workspace_entry(root, result["project"] / name, expected="file")
    if run_id:
        validated_run_id = validate_run_id(run_id)
        result["run"] = result["runs"] / validated_run_id
        result["state"] = result["run"] / "run.json"
        result["events"] = result["run"] / "events.jsonl"
        _assert_workspace_entry(root, result["run"], expected="dir")
        for name in (
            "run.json",
            "events.jsonl",
            "environment-audit.json",
            "checkpoint.json",
            "checkpoint.md",
            "final-report.md",
        ):
            _assert_workspace_entry(root, result["run"] / name, expected="file")
    return result


def _active_runs(root: Path) -> list[tuple[Path, Any]]:
    runs = _paths(root)["runs"]
    if not runs.exists():
        return []
    active: list[tuple[Path, Any]] = []
    for path in sorted(runs.glob("*/run.json")):
        _assert_workspace_entry(root, path.parent, expected="dir")
        _assert_workspace_entry(root, path, expected="file")
        state = load_state(path)
        if state.status is Status.RUNNING:
            active.append((path, state))
    return active


def _refresh_project_with_event(root: Path, path: Path, state: Any) -> None:
    migration = refresh_project_info(state, root)
    if migration:
        save_state(state, path)
        append_event(path.with_name("events.jsonl"), "project_identity_migrated", state.phase, migration)


def _record_phase_snapshot(state: Any, root: Path, target: Phase) -> dict[str, Any]:
    snapshots = state.progress.setdefault("phase_snapshots", {})
    if not isinstance(snapshots, dict):
        raise ValueError("Invalid phase_snapshots progress state")
    snapshot = {
        "timestamp": now_iso(),
        "workspace_fingerprint": workspace_fingerprint(root),
        "git_head": state.project.git_head,
    }
    snapshots[target.value] = snapshot
    return snapshot


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_finalization_project(root: Path, *, require_audit: bool) -> Path:
    """Validate the StackMarshal project-state boundary before any finalization I/O."""

    resolved_root = root.resolve(strict=True)
    state_dir = root / STATE_DIR
    project = state_dir / "project"
    for label, path in ((STATE_DIR, state_dir), (f"{STATE_DIR}/project", project)):
        if path.is_symlink():
            raise ValueError(f"{label} may not be a symlink")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"Missing finalization directory: {label}") from exc
        if resolved_root not in resolved.parents or not resolved.is_dir():
            raise ValueError(f"Finalization directory escapes workspace or is not a directory: {label}")

    required = [project / "task-graph.json", project / "task-graph.md"]
    audit = project / "environment-audit.json"
    if require_audit or audit.exists() or audit.is_symlink():
        required.append(audit)
    for path in required:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Finalization file is missing or unsafe: {path.relative_to(project).as_posix()}")
        resolved = path.resolve(strict=True)
        if project.resolve(strict=True) not in resolved.parents:
            raise ValueError(f"Finalization file escapes project state: {path.relative_to(project).as_posix()}")

    temporary = project / "task-graph.json.tmp"
    if temporary.is_symlink():
        raise ValueError("Finalization temporary task graph may not be a symlink")
    return project.resolve(strict=True)


def _finalization_files(root: Path) -> dict[str, Path]:
    project = _safe_finalization_project(root, require_audit=True)
    files: dict[str, Path] = {}
    pending = [project]
    visited_dirs = {project}
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold(), reverse=True):
            relative = path.relative_to(project)
            if path.is_symlink():
                raise ValueError(f"Finalization project evidence may not be a symlink: {relative}")
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise ValueError(f"Finalization project evidence changed while sealing: {relative}") from exc
            if resolved != project and project not in resolved.parents:
                raise ValueError(f"Finalization project evidence escapes project state: {relative}")
            if path.is_file():
                files[relative.as_posix()] = path
            elif path.is_dir():
                if resolved in visited_dirs:
                    raise ValueError(f"Finalization project evidence contains a directory alias or cycle: {relative}")
                visited_dirs.add(resolved)
                pending.append(path)
            else:
                raise ValueError(f"Finalization project evidence contains unsupported entry: {relative}")
    return files


def _finalization_snapshot(root: Path) -> dict[str, Any]:
    files = _finalization_files(root)
    return {
        "timestamp": now_iso(),
        "workspace_fingerprint": terminal_workspace_fingerprint(root),
        "files": {name: _sha256_file(path) for name, path in files.items()},
    }


def _finalization_errors(root: Path, state: Any) -> list[str]:
    finalization = state.progress.get("finalization")
    if not isinstance(finalization, dict):
        return ["missing_finalization"]
    errors: list[str] = []
    if finalization.get("workspace_fingerprint") != terminal_workspace_fingerprint(root):
        errors.append("workspace_changed_after_finalization")
    recorded = finalization.get("files")
    if not isinstance(recorded, dict):
        return [*errors, "invalid_finalization_file_hashes"]
    try:
        current_files = _finalization_files(root)
    except ValueError as exc:
        return [*errors, f"unsafe_finalization_project_evidence:{exc}"]
    if set(recorded) != set(current_files):
        errors.append("finalization_file_set_changed")
    for name, path in current_files.items():
        if recorded.get(name) != _sha256_file(path):
            errors.append(f"finalization_file_changed:{name}")
    return errors


def _completion_gate_errors(root: Path, state: Any, *, require_finalization: bool = True) -> list[str]:
    require_graph = state.mode is Mode.BUILD and int(state.progress.get("live_contract_version", 0)) >= 1
    errors: list[str] = []
    project_state_safe = True
    if require_graph:
        try:
            _safe_finalization_project(root, require_audit=False)
        except ValueError as exc:
            errors.append(f"unsafe_finalization_project:{exc}")
            project_state_safe = False
    if project_state_safe:
        errors.extend(task_completion_errors(root, require_graph=require_graph))
    errors.extend(completion_activity_errors(state))
    if state.mode is Mode.BUILD and require_graph:
        snapshots = state.progress.get("phase_snapshots", {})
        if not isinstance(snapshots, dict):
            errors.append("invalid_phase_snapshots")
        else:
            implementation = snapshots.get(Phase.IMPLEMENTATION.value)
            verification = snapshots.get(Phase.VERIFICATION.value)
            if not isinstance(implementation, dict) or not isinstance(verification, dict):
                errors.append("missing_live_phase_snapshots")
            elif implementation.get("workspace_fingerprint") == verification.get("workspace_fingerprint"):
                errors.append("no_workspace_change_during_implementation")
        verified_workspace = state.progress.get("verified_workspace")
        if not isinstance(verified_workspace, dict):
            errors.append("missing_verified_workspace_fingerprint")
        elif verified_workspace.get("workspace_fingerprint") != terminal_workspace_fingerprint(root):
            errors.append("workspace_changed_after_verification")
        if require_finalization:
            errors.extend(_finalization_errors(root, state))
    return errors


def cmd_init(args: argparse.Namespace) -> int:
    root = _root(args.root)
    paths = _paths(root)
    paths["project"].mkdir(parents=True, exist_ok=True)
    paths["runs"].mkdir(parents=True, exist_ok=True)
    if not paths["config"].exists():
        template = Path(__file__).with_name("data") / "stackmarshal.toml"
        shutil.copyfile(template, paths["config"])
    gitignore = root / ".gitignore"
    _assert_workspace_entry(root, gitignore, expected="file")
    marker = ".stackmarshal/runs/\n!.stackmarshal/runs/*/checkpoint.md\n!.stackmarshal/runs/*/checkpoint.json\n"
    if gitignore.exists():
        current = gitignore.read_text(encoding="utf-8")
        if ".stackmarshal/runs/" not in current:
            gitignore.write_text(current.rstrip() + "\n" + marker, encoding="utf-8")
    else:
        gitignore.write_text(marker, encoding="utf-8")
    _json({"initialized": True, "root": str(root), "config": str(paths["config"])})
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    root = _root(args.root)
    active = _active_runs(root)
    if active:
        path, existing = active[-1]
        _json({
            "started": False,
            "reason": "authoritative_run_already_active",
            "run_id": existing.run_id,
            "state": str(path),
        })
        return EXIT_INVALID_STATE
    if not validate_invocation(args.invocation):
        _json({"started": False, "reason": "explicit_invocation_required"})
        return EXIT_INVALID_INPUT
    config = default_config(args.budget) if args.budget else load_config(_paths(root)["config"])
    mode = Mode(args.mode) if args.mode else infer_mode(args.invocation)
    state = create_run(root, args.invocation, mode, config)
    paths = _paths(root, state.run_id)
    save_state(state, paths["state"])
    append_event(paths["events"], "run_created", state.phase, {"mode": mode.value})
    CodexAdapter(root).write_audit(paths["run"] / "environment-audit.json")
    _json({"started": True, "run_id": state.run_id, "state": str(paths["state"])})
    return 0


def _find_state(root: Path, run_id: str | None) -> tuple[Path, Any]:
    runs = _paths(root)["runs"]
    if run_id:
        selected = _paths(root, validate_run_id(run_id))
        path = selected["state"]
    else:
        candidates: list[Path] = []
        for candidate in runs.glob("*/run.json"):
            _assert_workspace_entry(root, candidate.parent, expected="dir")
            _assert_workspace_entry(root, candidate, expected="file")
            candidates.append(candidate)
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        if not candidates:
            raise FileNotFoundError("No StackMarshal run found")
        path = candidates[0]
        _paths(root, path.parent.name)
    return path, load_state(path)


def cmd_state_show(args: argparse.Namespace) -> int:
    path, state = _find_state(_root(args.root), args.run_id)
    _json({"path": str(path), "state": state.to_dict()})
    return 0


def cmd_state_transition(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path, state = _find_state(root, args.run_id)
    _refresh_project_with_event(root, path, state)
    target = Phase(args.phase)
    if target is Phase.COMPLETE:
        errors = _completion_gate_errors(root, state)
        if errors:
            _json({"transitioned": False, "target": target.value, "errors": errors})
            return EXIT_INVALID_STATE
        terminal_seal = terminal_repository_snapshot(root)
        state.progress["terminal_seal"] = terminal_seal
        snapshot = _record_phase_snapshot(state, root, target)
        state.progress["completion_gate"] = {
            "validated": True,
            "timestamp": now_iso(),
            "task_graph": "synchronized",
            "live_activity": "recorded",
            "finalization": "sealed",
            "terminal_seal": terminal_seal,
        }
    else:
        snapshot = _record_phase_snapshot(state, root, target)
    transition(state, target)
    save_state(state, path)
    append_event(
        path.with_name("events.jsonl"),
        "phase_transition",
        state.phase,
        {"target": state.phase.value, "workspace_snapshot": snapshot},
    )
    _json(state.to_dict())
    return EXIT_COMPLETE if state.status is Status.COMPLETE else 0


def cmd_budget_check(args: argparse.Namespace) -> int:
    _, state = _find_state(_root(args.root), args.run_id)
    decisions = [asdict(item) for item in check_budget(state.budget)]
    valid = all(item["allowed"] for item in decisions)
    _json({"valid": valid, "counters": decisions})
    return 0 if valid else EXIT_BUDGET


def _formal_budget_stop(root: Path, path: Path, state: Any, exc: ActivityBudgetExhausted) -> int:
    stop(
        state,
        Status.BUDGET_EXHAUSTED,
        f"Budget exhausted for {exc.counter}",
        {"counter": exc.counter, "attempted": exc.attempted, "limit": exc.limit},
    )
    save_state(state, path)
    checkpoint_json, checkpoint_md = create_checkpoint(
        state,
        path.parent,
        next_action="Reduce scope or start a new explicitly approved run.",
        do_not_repeat=[f"Do not exceed {exc.counter} limit {exc.limit} without a new approved run."],
    )
    append_event(
        path.with_name("events.jsonl"),
        "formal_stop",
        state.phase,
        {
            "status": Status.BUDGET_EXHAUSTED.value,
            "counter": exc.counter,
            "attempted": exc.attempted,
            "limit": exc.limit,
        },
    )
    _json({
        "status": Status.BUDGET_EXHAUSTED.value,
        "checkpoint": str(checkpoint_json),
        "markdown": str(checkpoint_md),
        "counter": exc.counter,
        "attempted": exc.attempted,
        "limit": exc.limit,
    })
    return EXIT_BUDGET


def cmd_activity_record(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path, state = _find_state(root, args.run_id)
    if state.status is not Status.RUNNING:
        raise ValueError(f"Cannot record activity for terminal run: {state.status.value}")
    _refresh_project_with_event(root, path, state)
    try:
        record = record_activity(
            state,
            args.kind,
            amount=args.amount,
            task_id=args.task_id,
            detail=args.detail,
        )
    except ActivityBudgetExhausted as exc:
        return _formal_budget_stop(root, path, state, exc)
    if args.kind == "verification":
        verified_workspace = {
            "timestamp": now_iso(),
            "workspace_fingerprint": terminal_workspace_fingerprint(root),
        }
        state.progress["verified_workspace"] = verified_workspace
        record["workspace_fingerprint"] = verified_workspace["workspace_fingerprint"]
    save_state(state, path)
    append_event(path.with_name("events.jsonl"), "activity_recorded", state.phase, record)
    _json({"recorded": True, "activity": record, "budget": state.budget.used})
    return 0


def cmd_task_add(args: argparse.Namespace) -> int:
    root = _root(args.root)
    _, state = _find_state(root, args.run_id)
    if state.status is not Status.RUNNING or state.phase is not Phase.TASK_GRAPH:
        raise ValueError("Tasks may be added only during TASK_GRAPH")
    task = add_task(
        root,
        args.task_id,
        args.summary,
        mandatory=not args.optional,
        acceptance=args.acceptance,
    )
    _json({"added": True, "task": task})
    return 0


def cmd_task_start(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path, state = _find_state(root, args.run_id)
    if state.status is not Status.RUNNING:
        raise ValueError(f"Cannot start task for terminal run: {state.status.value}")
    try:
        record = record_activity(state, "task-attempt", task_id=args.task_id, detail=args.detail)
    except ActivityBudgetExhausted as exc:
        return _formal_budget_stop(root, path, state, exc)
    attempts = state.progress.get("task_attempts", {})
    attempt = int(attempts.get(args.task_id, 0)) if isinstance(attempts, dict) else 0
    task = start_task(root, args.task_id, attempt)
    save_state(state, path)
    append_event(path.with_name("events.jsonl"), "task_started", state.phase, {**record, "task": task})
    _json({"started": True, "task": task, "attempt": attempt})
    return 0


def cmd_task_complete(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path, state = _find_state(root, args.run_id)
    if state.status is not Status.RUNNING or state.phase not in {Phase.IMPLEMENTATION, Phase.VERIFICATION}:
        raise ValueError("Tasks may be completed only during IMPLEMENTATION or VERIFICATION")
    task = complete_task(root, args.task_id, args.evidence)
    append_event(
        path.with_name("events.jsonl"),
        "task_completed",
        state.phase,
        {"task_id": args.task_id, "evidence": task.get("evidence", [])},
    )
    _json({"completed": True, "task": task})
    return 0


def cmd_task_block(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path, state = _find_state(root, args.run_id)
    if state.status is not Status.RUNNING:
        raise ValueError(f"Cannot block task for terminal run: {state.status.value}")
    task = block_task(root, args.task_id, args.reason)
    append_event(
        path.with_name("events.jsonl"),
        "task_blocked",
        state.phase,
        {"task_id": args.task_id, "reason": args.reason},
    )
    _json({"blocked": True, "task": task})
    return 0


def cmd_task_show(args: argparse.Namespace) -> int:
    graph = load_task_graph(_root(args.root), required=True)
    _json(graph)
    return 0


def _skill_version(path: Path) -> str | None:
    if not path.exists():
        return None
    match = re.search(r'^\s*version:\s*["\']?([^"\'\s]+)', path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def _default_managed_install_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "StackMarshal"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "stackmarshal"


def _normalized_path(path: Path) -> str:
    try:
        value = path.expanduser().resolve()
    except OSError:
        value = path.expanduser().absolute()
    return os.path.normcase(str(value))


def _read_managed_install_state(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = root / "install-state.json"
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"managed_install_state_unreadable:{exc.__class__.__name__}"
    if not isinstance(data, dict):
        return None, "managed_install_state_invalid"
    return data, None


def _launcher_package_version(path: Path) -> str | None:
    """Infer a launcher runtime version only from non-executing, high-confidence evidence."""
    normalized = _normalized_path(path)
    try:
        if path.suffix.casefold() in {".cmd", ".bat", ".sh"} or (os.name != "nt" and path.is_file()):
            with path.open("rb") as handle:
                text = handle.read(16_384).decode("utf-8", errors="replace")
            match = re.search(r"[\\/]versions[\\/]v(\d+\.\d+\.\d+)[\\/]", text)
            if match:
                return match.group(1)
    except OSError:
        pass

    current = Path(sys.argv[0])
    if current.exists() and _normalized_path(current) == normalized:
        return __version__
    return None


def _launcher_metadata_versions(path: Path) -> list[str]:
    """Return nearby installed-distribution versions without claiming launcher runtime identity."""
    parent = path.parent
    roots: list[Path] = []
    if parent.name.casefold() == "scripts":
        roots.append(parent.parent / "Lib" / "site-packages")
    elif parent.name == "bin":
        roots.extend(sorted((parent.parent / "lib").glob("python*/site-packages")))
    versions: set[str] = set()
    for site_packages in roots:
        if not site_packages.is_dir():
            continue
        try:
            for dist in distributions(path=[str(site_packages)]):
                metadata_name = dist.metadata["Name"]
                name = str(metadata_name or "").casefold().replace("_", "-")
                if name == "stackmarshal":
                    versions.add(dist.version)
        except (OSError, ValueError):
            continue
    return sorted(versions)


def _path_stackmarshal_candidates() -> list[dict[str, Any]]:
    names: tuple[str, ...]
    if os.name == "nt":
        names = ("stackmarshal.com", "stackmarshal.exe", "stackmarshal.bat", "stackmarshal.cmd")
    else:
        names = ("stackmarshal",)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_directory in os.environ.get("PATH", "").split(os.pathsep):
        if not raw_directory:
            continue
        directory = Path(raw_directory.strip('"')).expanduser()
        for name in names:
            candidate = directory / name
            try:
                is_file = candidate.is_file()
            except OSError:
                is_file = False
            if not is_file:
                continue
            key = _normalized_path(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "path": str(candidate),
                    "version": _launcher_package_version(candidate),
                    "metadata_versions": _launcher_metadata_versions(candidate),
                }
            )
    return candidates


def cmd_doctor(args: argparse.Namespace) -> int:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    skill_path = codex_home / "skills" / "stackmarshal" / "SKILL.md"
    restart_marker = codex_home / ".stackmarshal-restart-required.json"
    installed = _skill_version(skill_path)
    host = args.host_skill_version
    restart_required = host is not None and host != __version__
    restart_pending = restart_marker.is_file()
    marker_version: str | None = None
    if restart_pending:
        try:
            marker_data = json.loads(restart_marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            marker_data = {}
        if isinstance(marker_data, dict) and isinstance(marker_data.get("version"), str):
            marker_version = str(marker_data["version"])

    managed_root = _default_managed_install_root()
    managed_state, managed_state_error = _read_managed_install_state(managed_root)
    managed_version: str | None = None
    managed_launcher: str | None = None
    if managed_state is not None:
        value = managed_state.get("version")
        if isinstance(value, str):
            managed_version = value
        cli_state = managed_state.get("cli")
        if isinstance(cli_state, dict) and isinstance(cli_state.get("launcher"), str):
            managed_launcher = str(cli_state["launcher"])

    path_candidates = _path_stackmarshal_candidates()
    resolved_launcher = shutil.which("stackmarshal")
    resolved_launcher_version: str | None = None
    resolved_launcher_metadata_versions: list[str] = []
    if resolved_launcher is not None:
        resolved_key = _normalized_path(Path(resolved_launcher))
        for candidate in path_candidates:
            if _normalized_path(Path(str(candidate["path"]))) == resolved_key:
                value = candidate.get("version")
                resolved_launcher_version = str(value) if value else None
                metadata = candidate.get("metadata_versions", [])
                if isinstance(metadata, list):
                    resolved_launcher_metadata_versions = [str(item) for item in metadata]
                break
        if (
            resolved_launcher_version is None
            and managed_launcher is not None
            and _normalized_path(Path(managed_launcher)) == resolved_key
        ):
            resolved_launcher_version = managed_version

    known_versions = {__version__}
    if managed_version is not None:
        known_versions.add(managed_version)
    for candidate in path_candidates:
        version = candidate.get("version")
        if version:
            known_versions.add(str(version))
        metadata = candidate.get("metadata_versions", [])
        if isinstance(metadata, list):
            known_versions.update(str(item) for item in metadata if item)
    version_skew = len(known_versions) > 1
    repair_required = installed != __version__ or version_skew or managed_state_error is not None

    warnings: list[str] = []
    if version_skew:
        warnings.append("stackmarshal_version_skew")
    if len(path_candidates) > 1:
        warnings.append("multiple_stackmarshal_launchers_on_path")
    if resolved_launcher is not None and resolved_launcher_version is None:
        warnings.append("resolved_launcher_version_unverified")
    if managed_state_error is not None:
        warnings.append(managed_state_error)

    ready = not restart_required and not repair_required and not restart_pending
    _json({
        "ready": ready,
        "cli_version": __version__,
        "installed_skill_version": installed,
        "host_skill_version": host,
        "restart_required": restart_required or restart_pending,
        "restart_pending": restart_pending,
        "restart_marker_version": marker_version,
        "repair_required": repair_required,
        "version_skew": version_skew,
        "known_versions": sorted(known_versions),
        "invoked_cli": {
            "entrypoint": sys.argv[0],
            "python": sys.executable,
            "version": __version__,
        },
        "path_resolution": {
            "resolved_launcher": resolved_launcher,
            "resolved_launcher_version": resolved_launcher_version,
            "resolved_launcher_metadata_versions": resolved_launcher_metadata_versions,
            "candidates": path_candidates,
        },
        "managed_install": {
            "root": str(managed_root),
            "version": managed_version,
            "launcher": managed_launcher,
            "state_error": managed_state_error,
        },
        "warnings": warnings,
        "skill_path": str(skill_path),
    })
    return 0 if ready else EXIT_INVALID_STATE


def _read_json(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def cmd_candidate_score(args: argparse.Namespace) -> int:
    _json(score_candidate(_read_json(args.file)))
    return 0


def cmd_failure_fingerprint(args: argparse.Namespace) -> int:
    _json({"fingerprint": fingerprint(_read_json(args.file))})
    return 0


def cmd_progress_evaluate(args: argparse.Namespace) -> int:
    current = ProgressSnapshot(**_read_json(args.current))
    previous = ProgressSnapshot(**_read_json(args.previous)) if args.previous else None
    _json(evaluate(previous, current))
    return 0


def cmd_lock_verify(args: argparse.Namespace) -> int:
    result = verify_lock(Path(args.file), _root(args.root))
    _json(result)
    return 0 if result["valid"] else EXIT_UNSAFE


def cmd_checkpoint_create(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path, state = _find_state(root, args.run_id)
    if state.status is Status.RUNNING:
        state.status = Status.CHECKPOINT_READY
        state.phase = Phase.CHECKPOINTING
        save_state(state, path)
    json_path, markdown_path = create_checkpoint(
        state, path.parent, next_action=args.next_action, do_not_repeat=args.do_not_repeat
    )
    append_event(path.with_name("events.jsonl"), "checkpoint_created", state.phase, {"path": str(json_path)})
    _json({"checkpoint": str(json_path), "markdown": str(markdown_path)})
    return EXIT_CHECKPOINT


def cmd_resume_inspect(args: argparse.Namespace) -> int:
    root = _root(args.root)
    checkpoint = Path(args.file) if args.file else _find_state(root, args.run_id)[0].with_name("checkpoint.json")
    _json(inspect_checkpoint(checkpoint, root))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    result = validate_json_file(Path(args.file), args.kind)
    _json(result)
    return 0 if result["valid"] else EXIT_INVALID_STATE


def cmd_audit(args: argparse.Namespace) -> int:
    root = _root(args.root)
    output = Path(args.output) if args.output else root / STATE_DIR / "project" / "environment-audit.json"
    CodexAdapter(root).write_audit(output)
    _json({"written": str(output)})
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    root = _root(args.root)
    try:
        path, state = _find_state(root, args.run_id)
        if state.status is not Status.RUNNING or state.phase is not Phase.VERIFICATION:
            _json({
                "finalized": False,
                "reason": "finalization_requires_running_verification",
                "status": state.status.value,
                "phase": state.phase.value,
            })
            return EXIT_INVALID_STATE
        _refresh_project_with_event(root, path, state)
        errors = _completion_gate_errors(root, state, require_finalization=False)
        if errors:
            _json({"finalized": False, "errors": errors})
            return EXIT_INVALID_STATE
        graph = load_task_graph(root, required=True)
        save_task_graph(root, graph)
        CodexAdapter(root).write_audit(root / STATE_DIR / "project" / "environment-audit.json")
        _refresh_project_with_event(root, path, state)
        finalization = _finalization_snapshot(root)
        state.progress["finalization"] = finalization
        save_state(state, path)
        append_event(
            path.with_name("events.jsonl"),
            "finalization_completed",
            state.phase,
            finalization,
        )
    except ValueError as exc:
        _json({"finalized": False, "errors": [str(exc)]})
        return EXIT_INVALID_STATE
    _json({"finalized": True, "run_id": state.run_id, "finalization": finalization})
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path, state = _find_state(root, args.run_id)
    status = Status(args.status)
    stop(state, status, args.reason)
    save_state(state, path)
    checkpoint_json, checkpoint_md = create_checkpoint(
        state,
        path.parent,
        next_action=args.next_action,
        do_not_repeat=args.do_not_repeat,
    )
    append_event(
        path.with_name("events.jsonl"),
        "formal_stop",
        state.phase,
        {"status": status.value, "reason": args.reason},
    )
    _json({
        "status": status.value,
        "checkpoint": str(checkpoint_json),
        "markdown": str(checkpoint_md),
    })
    exit_codes = {
        Status.BUDGET_EXHAUSTED: EXIT_BUDGET,
        Status.APPROVAL_REQUIRED: EXIT_APPROVAL,
        Status.UNSAFE_DEPENDENCY: EXIT_UNSAFE,
        Status.BLOCKED_EXTERNAL: EXIT_EXTERNAL,
    }
    return exit_codes.get(status, EXIT_CHECKPOINT)


def cmd_report(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path, state = _find_state(root, args.run_id)
    report_path = path.parent / "final-report.md"
    report = f"""# StackMarshal Run Report

- Run: `{state.run_id}`
- Mode: `{state.mode.value}`
- Phase: `{state.phase.value}`
- Status: `{state.status.value}`
- Project: `{state.project.root}`
- Git HEAD: `{state.project.git_head or 'none'}`

## Budget

```json
{json.dumps({'used': state.budget.used, 'remaining': state.budget.remaining()}, indent=2)}
```

## Progress

```json
{json.dumps(state.progress, indent=2, ensure_ascii=False)}
```

## Stop reason

```json
{json.dumps(state.stop_reason, indent=2, ensure_ascii=False)}
```
"""
    report_path.write_text(report, encoding="utf-8")
    _json({"report": str(report_path), "status": state.status.value})
    return EXIT_COMPLETE if state.status is Status.COMPLETE else 0


def cmd_invocation(args: argparse.Namespace) -> int:
    triggered = validate_invocation(args.text)
    _json({"triggered": triggered, "mode": infer_mode(args.text).value if triggered else None})
    return 0 if triggered else EXIT_INVALID_INPUT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stackmarshal")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)
    start = sub.add_parser("start")
    start.add_argument("--mode", choices=[item.value for item in Mode])
    start.add_argument("--budget", choices=["quick", "standard", "deep"])
    start.add_argument("--invocation", required=True)
    start.set_defaults(func=cmd_start)

    state = sub.add_parser("state")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    show = state_sub.add_parser("show")
    show.add_argument("--run-id")
    show.set_defaults(func=cmd_state_show)
    move = state_sub.add_parser("transition")
    move.add_argument("phase", choices=[item.value for item in Phase])
    move.add_argument("--run-id")
    move.set_defaults(func=cmd_state_transition)

    budget = sub.add_parser("budget")
    budget_sub = budget.add_subparsers(dest="budget_command", required=True)
    budget_check = budget_sub.add_parser("check")
    budget_check.add_argument("--run-id")
    budget_check.set_defaults(func=cmd_budget_check)

    activity = sub.add_parser("activity")
    activity_sub = activity.add_subparsers(dest="activity_command", required=True)
    activity_record = activity_sub.add_parser("record")
    activity_record.add_argument(
        "kind",
        choices=[
            "tool-call",
            "implementation",
            "verification",
            "task-attempt",
            "research-round",
            "architecture-replan",
            "failure-repeat",
            "stagnation-cycle",
            "scope-addition",
        ],
    )
    activity_record.add_argument("--run-id")
    activity_record.add_argument("--amount", type=int, default=1)
    activity_record.add_argument("--task-id")
    activity_record.add_argument("--detail")
    activity_record.set_defaults(func=cmd_activity_record)

    task = sub.add_parser("task")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_add = task_sub.add_parser("add")
    task_add.add_argument("task_id")
    task_add.add_argument("--run-id")
    task_add.add_argument("--summary", required=True)
    task_add.add_argument("--acceptance", action="append", default=[])
    task_add.add_argument("--optional", action="store_true")
    task_add.set_defaults(func=cmd_task_add)
    task_start = task_sub.add_parser("start")
    task_start.add_argument("task_id")
    task_start.add_argument("--run-id")
    task_start.add_argument("--detail")
    task_start.set_defaults(func=cmd_task_start)
    task_complete = task_sub.add_parser("complete")
    task_complete.add_argument("task_id")
    task_complete.add_argument("--run-id")
    task_complete.add_argument("--evidence", action="append", default=[])
    task_complete.set_defaults(func=cmd_task_complete)
    task_block = task_sub.add_parser("block")
    task_block.add_argument("task_id")
    task_block.add_argument("--run-id")
    task_block.add_argument("--reason", required=True)
    task_block.set_defaults(func=cmd_task_block)
    task_show = task_sub.add_parser("show")
    task_show.set_defaults(func=cmd_task_show)

    candidate = sub.add_parser("candidate")
    candidate_sub = candidate.add_subparsers(dest="candidate_command", required=True)
    candidate_score = candidate_sub.add_parser("score")
    candidate_score.add_argument("file")
    candidate_score.set_defaults(func=cmd_candidate_score)

    failure = sub.add_parser("failure")
    failure_sub = failure.add_subparsers(dest="failure_command", required=True)
    failure_fp = failure_sub.add_parser("fingerprint")
    failure_fp.add_argument("file")
    failure_fp.set_defaults(func=cmd_failure_fingerprint)

    progress = sub.add_parser("progress")
    progress_sub = progress.add_subparsers(dest="progress_command", required=True)
    progress_eval = progress_sub.add_parser("evaluate")
    progress_eval.add_argument("current")
    progress_eval.add_argument("--previous")
    progress_eval.set_defaults(func=cmd_progress_evaluate)

    lock = sub.add_parser("lock")
    lock_sub = lock.add_subparsers(dest="lock_command", required=True)
    lock_verify = lock_sub.add_parser("verify")
    lock_verify.add_argument("file")
    lock_verify.set_defaults(func=cmd_lock_verify)

    checkpoint = sub.add_parser("checkpoint")
    checkpoint_sub = checkpoint.add_subparsers(dest="checkpoint_command", required=True)
    checkpoint_create = checkpoint_sub.add_parser("create")
    checkpoint_create.add_argument("--run-id")
    checkpoint_create.add_argument("--next-action", required=True)
    checkpoint_create.add_argument("--do-not-repeat", action="append", default=[])
    checkpoint_create.set_defaults(func=cmd_checkpoint_create)

    resume = sub.add_parser("resume")
    resume_sub = resume.add_subparsers(dest="resume_command", required=True)
    resume_inspect = resume_sub.add_parser("inspect")
    resume_inspect.add_argument("--run-id")
    resume_inspect.add_argument("--file")
    resume_inspect.set_defaults(func=cmd_resume_inspect)

    validate = sub.add_parser("validate")
    validate.add_argument("file")
    validate.add_argument(
        "--kind",
        choices=["run-state", "candidate", "capability-map", "task-graph", "checkpoint"],
        default="run-state",
    )
    validate.set_defaults(func=cmd_validate)

    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("status", choices=[item.value for item in Status if item not in {Status.RUNNING, Status.COMPLETE}])
    stop_parser.add_argument("--run-id")
    stop_parser.add_argument("--reason", required=True)
    stop_parser.add_argument("--next-action", required=True)
    stop_parser.add_argument("--do-not-repeat", action="append", default=[])
    stop_parser.set_defaults(func=cmd_stop)

    report = sub.add_parser("report")
    report.add_argument("--run-id")
    report.set_defaults(func=cmd_report)

    audit = sub.add_parser("audit")
    audit.add_argument("--output")
    audit.set_defaults(func=cmd_audit)

    finalize = sub.add_parser("finalize")
    finalize.add_argument("--run-id")
    finalize.set_defaults(func=cmd_finalize)

    invocation = sub.add_parser("invocation")
    invocation.add_argument("text")
    invocation.set_defaults(func=cmd_invocation)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--host-skill-version")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        func: Callable[[argparse.Namespace], int] = args.func
        return func(args)
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_INVALID_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
