# Nextpatch Experimental Report — v1.1.1 Candidate

## Purpose

This experiment validates the live-execution fixes discovered during RepoHealth Case Study #1 before the candidate is committed or published.

The failure shape was reproduced deliberately: a requested empty child workspace was created beneath an unrelated parent Git repository, StackMarshal was started before the child had its own repository, and the child repository was bootstrapped during the same bounded build.

## Candidate changes under test

- Nested workspaces no longer inherit an ancestor Git repository as project ownership.
- One authoritative `RUNNING` run owns a bounded job; a second `start` is rejected.
- Child repository bootstrap and the first root commit migrate repository lineage inside the same run and append explicit migration events.
- Phase transitions record workspace fingerprints at the live boundary.
- Observable host activity consumes the Core budget ledger.
- Per-task attempts are bounded and recorded.
- `task-graph.json` is canonical; `task-graph.md` is generated from it.
- `COMPLETE` rejects pending mandatory tasks, missing evidence, untouched live budgets, missing implementation/verification activity, and an implementation interval with no observable workspace change.
- Installer-managed Skill changes create a restart-pending marker outside the Skill directory; the fallback refuses invocation until a matching newly loaded Skill acknowledges it.
- `doctor --host-skill-version` additionally detects Skill/CLI/host-session version mismatch.

## Automated quality evidence

Before the fresh-workspace experiment:

- `pytest`: 69 passed, 2 skipped. The two skips are the existing Windows normal-user symlink privilege skips.
- Ruff: PASS.
- strict mypy: PASS across 23 source files.
- branch-aware coverage: 89%, above the 85% release gate.
- wheel and sdist build: PASS for `1.1.1`.
- Twine package checks: PASS.

## Fresh nested-workspace experiment

The dedicated integration experiment was executed twice, including once with its temporary workspace persisted under the local, Git-excluded `phase3b-lab` for independent inspection.

Observed terminal run:

- exactly one run directory,
- final status `COMPLETE`,
- requested child recognized initially as `repository_owned=false`,
- child `git init` recorded as `workspace_repository_bootstrap`,
- first child commit recorded as `repository_first_commit`,
- no replacement/orphan `RUNNING` run,
- implementation phase recorded 4 observable tool calls,
- verification phase recorded 2 observable tool calls,
- final `tool_calls` usage = 6,
- per-task attempt usage = 1,
- implementation and verification workspace fingerprints differ,
- both mandatory tasks are `done` with evidence,
- completion gate recorded `validated=true`.

The append-only event log preserves the actual order: run creation, live phase transitions, identity migration, task start, budget/activity records, task completion, first-commit migration, verification, and terminal `COMPLETE`.

## Restart-readiness check

The candidate CLI (`1.1.1`) was checked against the currently installed/host-loaded `1.1.0` Skill. `doctor --host-skill-version 1.1.0` correctly returned not-ready with both `restart_required=true` and `repair_required=true` instead of allowing silent emulation.

The dependency-free fallback was also tested with a versioned restart-pending marker. While the marker existed, an ordinary `$stackmarshal build` invocation was refused. A stale `1.1.0` host acknowledgement could not clear the marker; a matching `1.1.1` acknowledgement cleared it and subsequent invocation succeeded. This covers the operator-error shape where the Skill files have been replaced on disk but Codex has not yet reloaded them.

## Scope and limitation

`tool_calls` is an observable, Core-recorded activity budget. The v1 Codex adapter does not intercept every native host tool call automatically, so the Skill reserves/records bounded host-tool batches through the Core before use. StackMarshal does not claim host-level interception that the adapter cannot technically provide.

The deterministic release builder is intentionally deferred until the candidate files are locally committed, because the release source archive is built from Git-tracked files. Running it before that commit would omit new candidate files and produce invalid evidence.

## Result

**PASS — ready for a local candidate commit and post-commit release-build verification.**

No GitHub push or release was performed as part of this experiment.
