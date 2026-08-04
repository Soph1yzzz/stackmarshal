#!/usr/bin/env python3
"""Initialize a formal run with the installed StackMarshal CLI."""

from _cli_wrapper import run_with_prefix

if __name__ == "__main__":
    raise SystemExit(run_with_prefix(["start"]))
