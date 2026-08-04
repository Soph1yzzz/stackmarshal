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


def project_info(root: Path) -> ProjectInfo:
    resolved = root.resolve()
    head = _run_git(resolved, "rev-parse", "HEAD")
    status = _run_git(resolved, "status", "--porcelain")
    identity_seed = str(resolved)
    identity = hashlib.sha256(identity_seed.encode()).hexdigest()
    return ProjectInfo(str(resolved), head, identity, bool(status))


def new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def create_run(root: Path, invocation: str, mode: Mode, config: Config) -> RunState:
    timestamp = now_iso()
    return RunState(
        schema_version=SCHEMA_VERSION,
        run_id=new_run_id(),
        project=project_info(root),
        invocation=Invocation(explicit=True, raw_text=invocation),
        mode=mode,
        budget=BudgetState(config.budget_profile, dict(config.limits), {}),
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
