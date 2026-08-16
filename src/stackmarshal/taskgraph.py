from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from .constants import STATE_DIR

TASK_STATUSES = {"pending", "in_progress", "done", "blocked"}


def task_graph_path(root: Path) -> Path:
    return root.resolve() / STATE_DIR / "project" / "task-graph.json"


def task_graph_markdown_path(root: Path) -> Path:
    return root.resolve() / STATE_DIR / "project" / "task-graph.md"


def empty_graph() -> dict[str, Any]:
    return {"schema_version": "1.0", "tasks": []}


def load_task_graph(root: Path, *, required: bool = False) -> dict[str, Any]:
    path = task_graph_path(root)
    if not path.exists():
        if required:
            raise ValueError("Missing canonical task graph: .stackmarshal/project/task-graph.json")
        return empty_graph()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ValueError("Invalid task graph schema")
    tasks = raw.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("Invalid task graph tasks")
    seen: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Invalid task graph entry")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
            raise ValueError("Task ids must be unique non-empty strings")
        seen.add(task_id)
        if task.get("status", "pending") not in TASK_STATUSES:
            raise ValueError(f"Invalid task status for {task_id}")
        if not isinstance(task.get("mandatory", True), bool):
            raise ValueError(f"Invalid mandatory flag for {task_id}")
        if not isinstance(task.get("acceptance", []), list) or not isinstance(task.get("evidence", []), list):
            raise ValueError(f"Invalid task acceptance/evidence for {task_id}")
    return raw


def save_task_graph(root: Path, graph: dict[str, Any]) -> None:
    path = task_graph_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    task_graph_markdown_path(root).write_text(render_markdown(graph), encoding="utf-8")


def add_task(
    root: Path,
    task_id: str,
    summary: str,
    *,
    mandatory: bool = True,
    acceptance: list[str] | None = None,
) -> dict[str, Any]:
    graph = load_task_graph(root)
    if any(task["id"] == task_id for task in graph["tasks"]):
        raise ValueError(f"Task already exists: {task_id}")
    task = {
        "id": task_id,
        "summary": summary,
        "mandatory": mandatory,
        "acceptance": list(acceptance or []),
        "status": "pending",
        "attempts": 0,
        "evidence": [],
    }
    graph["tasks"].append(task)
    save_task_graph(root, graph)
    return task


def _find_task(graph: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in graph["tasks"]:
        if isinstance(task, dict) and task.get("id") == task_id:
            return cast(dict[str, Any], task)
    raise ValueError(f"Unknown task: {task_id}")


def start_task(root: Path, task_id: str, attempt: int) -> dict[str, Any]:
    graph = load_task_graph(root, required=True)
    task = _find_task(graph, task_id)
    if task["status"] == "done":
        raise ValueError(f"Task is already complete: {task_id}")
    if task["status"] == "blocked":
        raise ValueError(f"Task is blocked: {task_id}")
    task["status"] = "in_progress"
    task["attempts"] = attempt
    save_task_graph(root, graph)
    return task


def complete_task(root: Path, task_id: str, evidence: list[str]) -> dict[str, Any]:
    graph = load_task_graph(root, required=True)
    task = _find_task(graph, task_id)
    if task["status"] not in {"pending", "in_progress"}:
        raise ValueError(f"Task cannot be completed from status {task['status']}: {task_id}")
    merged = [str(item).strip() for item in evidence if str(item).strip()]
    if task.get("mandatory", True) and not merged:
        raise ValueError(f"Mandatory task requires evidence: {task_id}")
    task["status"] = "done"
    task["evidence"] = merged
    save_task_graph(root, graph)
    return task


def block_task(root: Path, task_id: str, reason: str) -> dict[str, Any]:
    graph = load_task_graph(root, required=True)
    task = _find_task(graph, task_id)
    task["status"] = "blocked"
    task["evidence"] = [reason]
    save_task_graph(root, graph)
    return task


def completion_errors(root: Path, *, require_graph: bool) -> list[str]:
    path = task_graph_path(root)
    if not path.exists():
        return ["missing_task_graph"] if require_graph else []
    graph = load_task_graph(root, required=True)
    errors: list[str] = []
    for task in graph["tasks"]:
        if not task.get("mandatory", True):
            continue
        status = task.get("status")
        if status != "done":
            errors.append(f"mandatory_task_not_done:{task['id']}:{status}")
        elif not task.get("evidence"):
            errors.append(f"mandatory_task_missing_evidence:{task['id']}")
    if require_graph and not graph["tasks"]:
        errors.append("empty_task_graph")
    return errors


def render_markdown(graph: dict[str, Any]) -> str:
    lines = ["# Task Graph", "", "Canonical source: `task-graph.json`.", ""]
    if not graph["tasks"]:
        lines.append("No tasks recorded.")
        return "\n".join(lines) + "\n"
    for task in graph["tasks"]:
        marker = "x" if task.get("status") == "done" else " "
        required = "mandatory" if task.get("mandatory", True) else "optional"
        lines.append(f"- [{marker}] `{task['id']}` — {task.get('summary', '')} ({required}, status={task.get('status')})")
        for criterion in task.get("acceptance", []):
            lines.append(f"  - acceptance: {criterion}")
        for evidence in task.get("evidence", []):
            lines.append(f"  - evidence: {evidence}")
    return "\n".join(lines) + "\n"
