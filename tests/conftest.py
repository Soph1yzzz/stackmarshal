from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_stackmarshal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep checkpoint signing keys and user state isolated from the developer machine."""

    monkeypatch.setenv("STACKMARSHAL_STATE_HOME", str(tmp_path / "user-state"))
    monkeypatch.delenv("STACKMARSHAL_CHECKPOINT_KEY_FILE", raising=False)
