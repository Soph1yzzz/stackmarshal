#!/usr/bin/env python3
"""Run the repository's deterministic quality gates."""

from __future__ import annotations

import subprocess
import sys

COMMANDS = [
    [sys.executable, "-m", "pytest", "-q"],
    [sys.executable, "-m", "mypy", "src/stackmarshal"],
    [sys.executable, "-m", "ruff", "check", "src", "tests"],
]

if __name__ == "__main__":
    for command in COMMANDS:
        result = subprocess.run(command, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)
    raise SystemExit(0)
