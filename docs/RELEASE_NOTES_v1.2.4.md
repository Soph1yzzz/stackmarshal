# StackMarshal v1.2.4 — Invocation and continuation correctness (candidate)

Status: **unreleased**. The source and test evidence below describe the local
candidate; they are not a GitHub Release, installed upgrade, or published tag.

## Problem

v1.2.3 missed ordinary explicit Japanese mechanism requests such as
`StackMarshalを利用して開発して` and `StackMarshalで進めて`. It also could not
distinguish a fresh invocation from a context-bound request to keep working on
an existing signed run. A bare `triggered:false` concealed why admission failed.

## Changes

- Align Core and dependency-free Skill fallback on a bounded explicit method
  grammar, explicit non-use rejection, and conservative treatment of quoted
  examples and references.
- Return `reason` and `continuation: not_evaluated` from the new-invocation
  check, while keeping `triggered` and `mode`.
- Add `stackmarshal --root PROJECT continuation "そのまま進めて" --run-id RUN_ID`.
  It is read-only and admits only one existing HMAC-verified RUNNING run that
  matches the selected project, original explicit invocation, and known run ID.
- Update Skill guidance to separate new work from continuation. Checkpoint
  resume and all command authorization remain independent.

## Validation and limitations

The local Windows source run passed 215 tests with 6 environment-dependent
symlink tests skipped; Ruff and strict mypy passed. Branch coverage reached the
configured 85% project threshold when coverage was run with the explicit
`--source=src/stackmarshal` path. The wheel and sdist were built locally
and passed Twine metadata checks; multi-OS CI, CodeQL, and publication remain
separate release gates.

Natural-language admission remains a conservative grammar, not a general
semantic model. The CLI authenticates run state, not conversation identity;
the Skill must supply the ID of the run already approved for the same task.
