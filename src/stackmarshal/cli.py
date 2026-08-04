from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
from typing import Any

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
    save_state,
    stop,
    transition,
    validate_invocation,
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


def _paths(root: Path, run_id: str | None = None) -> dict[str, Path]:
    base = root / STATE_DIR
    result = {
        "base": base,
        "config": base / "config.toml",
        "project": base / "project",
        "runs": base / "runs",
    }
    if run_id:
        result["run"] = result["runs"] / run_id
        result["state"] = result["run"] / "run.json"
        result["events"] = result["run"] / "events.jsonl"
    return result


def cmd_init(args: argparse.Namespace) -> int:
    root = _root(args.root)
    paths = _paths(root)
    paths["project"].mkdir(parents=True, exist_ok=True)
    paths["runs"].mkdir(parents=True, exist_ok=True)
    if not paths["config"].exists():
        template = Path(__file__).with_name("data") / "stackmarshal.toml"
        shutil.copyfile(template, paths["config"])
    gitignore = root / ".gitignore"
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
    if not validate_invocation(args.invocation):
        _json({"started": False, "reason": "explicit_invocation_required"})
        return EXIT_INVALID_INPUT
    config = load_config(_paths(root)["config"])
    mode = Mode(args.mode) if args.mode else infer_mode(args.invocation)
    if args.budget:
        config = default_config(args.budget)
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
        path = runs / run_id / "run.json"
    else:
        candidates = sorted(runs.glob("*/run.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not candidates:
            raise FileNotFoundError("No StackMarshal run found")
        path = candidates[0]
    return path, load_state(path)


def cmd_state_show(args: argparse.Namespace) -> int:
    path, state = _find_state(_root(args.root), args.run_id)
    _json({"path": str(path), "state": state.to_dict()})
    return 0


def cmd_state_transition(args: argparse.Namespace) -> int:
    root = _root(args.root)
    path, state = _find_state(root, args.run_id)
    transition(state, Phase(args.phase))
    save_state(state, path)
    append_event(path.with_name("events.jsonl"), "phase_transition", state.phase, {"target": state.phase.value})
    _json(state.to_dict())
    return EXIT_COMPLETE if state.status is Status.COMPLETE else 0


def cmd_budget_check(args: argparse.Namespace) -> int:
    _, state = _find_state(_root(args.root), args.run_id)
    decisions = [asdict(item) for item in check_budget(state.budget)]
    valid = all(item["allowed"] for item in decisions)
    _json({"valid": valid, "counters": decisions})
    return 0 if valid else EXIT_BUDGET


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
    validate.add_argument("--kind", choices=["run-state", "candidate", "capability-map", "checkpoint"], default="run-state")
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

    invocation = sub.add_parser("invocation")
    invocation.add_argument("text")
    invocation.set_defaults(func=cmd_invocation)
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
