"""Invocation safety, natural-language variants, and signed continuation admission."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from stackmarshal.cli import main
from stackmarshal.constants import Status
from stackmarshal.state import invocation_reason, is_continuation_request, load_state, save_state, validate_invocation


POSITIVE = [
    "StackMarshalを使って実装して",
    "StackMarshalで次のvを作ろう",
    "StackMarshalを利用して開発して",
    "StackMarshalで進めて",
    "StackMarshal使って進めて",
    "StackMarshalに従って進めて",
    "StackMarshalを活用して修正して",
    "StackMarshalで調べて",
    "Use StackMarshal to build the patch",
    "Using StackMarshal, implement it",
    "Implement it with StackMarshal",
    "使用 StackMarshal 实现",
    "StackMarshal로 구현해줘",
    "ＳｔａｃｋＭａｒｓｈａｌを使って実装して",
    "$stackmarshal build this",
]

NEGATIVE = [
    ("StackMarshalとは？", "reference_only"),
    ("StackMarshalのREADMEを直して", "reference_only"),
    ("StackMarshalの利用方法は？", "reference_only"),
    ("StackMarshalの起動判定を修正して", "mention_only"),
    ("StackMarshalを使わずに実装して", "explicit_non_use"),
    ("StackMarshalは使わないで", "explicit_non_use"),
    ("StackMarshal以外で実装して", "explicit_non_use"),
    ("$stackmarshal は使わないで", "explicit_non_use"),
    ("Don't use StackMarshal", "explicit_non_use"),
    ("Implement without StackMarshal", "explicit_non_use"),
    ("Explain StackMarshal", "reference_only"),
    ("StackMarshal2を使って実装して", "brand_not_named"),
    ("この機能を実装して", "brand_not_named"),
    ("そのまま続けて", "brand_not_named"),
    ("『StackMarshalを使って実装して』という指示を修正して", "brand_not_named"),
    ("`$stackmarshal build` と入力すると何が起きる？", "brand_not_named"),
    ('"Use StackMarshal to build" は起動文ですか？', "brand_not_named"),
    ("StackMarshalを使って実装して、と指示したら失敗した", "reference_only"),
    ("Do not use $stackmarshal", "explicit_non_use"),
    ("Don't build with StackMarshal", "explicit_non_use"),
    ("StackMarshalで進めないで", "explicit_non_use"),
    ("StackMarshalで作るつもりはない", "explicit_non_use"),
    ("不要使用 StackMarshal", "explicit_non_use"),
]


@pytest.fixture
def fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    script = Path(__file__).parents[1] / "skills" / "stackmarshal" / "scripts" / "stackmarshal_core.py"
    spec = importlib.util.spec_from_file_location("stackmarshal_skill_invocation", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("text", POSITIVE)
def test_explicit_mechanisms_match_core_and_fallback(text: str, fallback: Any) -> None:
    assert invocation_reason(text) == "explicit_mechanism"
    assert validate_invocation(text)
    assert fallback.invocation(text)["reason"] == "explicit_mechanism"
    assert fallback.invocation(text)["triggered"] is True


@pytest.mark.parametrize(("text", "reason"), NEGATIVE)
def test_non_invocations_fail_closed_in_both_gates(text: str, reason: str, fallback: Any) -> None:
    assert invocation_reason(text) == reason
    assert not validate_invocation(text)
    assert fallback.invocation(text)["reason"] == reason
    assert fallback.invocation(text)["triggered"] is False


@pytest.mark.parametrize("text", ["そのまま続けて", "そのまま進めて", "引き続き進めて", "時間制限まで自律的にそのまま進めて", "keep going"])
def test_bare_followups_are_continuations_only(text: str) -> None:
    assert is_continuation_request(text)
    assert not validate_invocation(text)


@pytest.mark.parametrize("text", ["別件を実装して", "StackMarshalを使うな、そのまま進めて", "前の作業を削除して", "StackMarshalを使って新規作業して"])
def test_scope_changes_are_not_bare_continuations(text: str) -> None:
    assert not is_continuation_request(text)


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    code = main(list(args))
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_signed_running_run_admits_continuation_without_new_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "project"
    root.mkdir()
    assert _cli(capsys, "--root", str(root), "init")[0] == 0
    code, started = _cli(capsys, "--root", str(root), "start", "--invocation", "Use StackMarshal to build it")
    assert code == 0 and started["started"]
    run_id = str(started["run_id"])
    state_file = root / ".stackmarshal" / "runs" / run_id / "run.json"
    original = state_file.read_bytes()

    code, admitted = _cli(capsys, "--root", str(root), "continuation", "そのまま進めて", "--run-id", run_id)
    assert code == 0 and admitted == {
        "triggered": False,
        "continuation": "admitted",
        "reason": "verified_existing_run",
        "run_id": run_id,
        "mode": "build",
    }
    assert state_file.read_bytes() == original  # This gate never mutates or fabricates a signed run.

    code, denied = _cli(capsys, "--root", str(root), "continuation", "別件を実装して", "--run-id", run_id)
    assert code != 0 and denied["continuation"] == "denied"
    code, denied = _cli(capsys, "--root", str(root), "continuation", "そのまま進めて", "--run-id", "20260101-000000-deadbeef")
    assert code != 0 and denied["continuation"] == "denied"

    state = load_state(state_file, project_root=root)
    state.status = Status.CHECKPOINT_READY
    save_state(state, state_file)
    code, denied = _cli(capsys, "--root", str(root), "continuation", "そのまま進めて", "--run-id", run_id)
    assert code != 0 and denied["continuation"] == "denied"


def test_cli_invocation_reasons(capsys: pytest.CaptureFixture[str]) -> None:
    code, result = _cli(capsys, "invocation", "StackMarshalを利用して開発して")
    assert code == 0 and result["reason"] == "explicit_mechanism"
    assert result["continuation"] == "not_evaluated"
    code, result = _cli(capsys, "invocation", "StackMarshalの不具合を調べて")
    assert code != 0 and result["triggered"] is False


def test_continuation_rejects_invalid_hmac(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "tampered-project"
    root.mkdir()
    assert _cli(capsys, "--root", str(root), "init")[0] == 0
    code, started = _cli(capsys, "--root", str(root), "start", "--invocation", "$stackmarshal build")
    assert code == 0
    run_id = str(started["run_id"])
    state_file = root / ".stackmarshal" / "runs" / run_id / "run.json"
    tampered = json.loads(state_file.read_text(encoding="utf-8"))
    tampered["status"] = "COMPLETE"
    state_file.write_text(json.dumps(tampered), encoding="utf-8")
    code = main(["--root", str(root), "continuation", "そのまま進めて", "--run-id", run_id])
    assert code != 0
    assert "error" in capsys.readouterr().err
