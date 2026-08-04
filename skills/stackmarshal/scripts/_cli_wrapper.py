from __future__ import annotations

from collections.abc import Sequence
import sys

from stackmarshal.cli import main


def run_with_prefix(prefix: Sequence[str]) -> int:
    """Forward global CLI options before a wrapper's fixed subcommand."""
    args = list(sys.argv[1:])
    global_args: list[str] = []
    if "--root" in args:
        index = args.index("--root")
        if index + 1 >= len(args):
            return main(["--root"])
        global_args = args[index : index + 2]
        del args[index : index + 2]
    return main([*global_args, *prefix, *args])
