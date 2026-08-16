# StackMarshal v1.1.1

StackMarshal v1.1.1 is a live-orchestration hardening patch derived from the RepoHealth Case Study #1 dogfooding run.

## What changed

- Nested requested workspaces no longer silently inherit an ancestor Git repository as project ownership.
- One authoritative `RUNNING` run owns a bounded job; duplicate starts fail closed.
- Repository bootstrap and first-commit lineage changes stay inside the same run with explicit migration events.
- Live phase transitions record workspace fingerprints so retrospective phase replay is distinguishable from implementation that actually occurred between boundaries.
- Observable Codex activity is wired to the Core budget ledger, including tool batches, research rounds, replans, repeated failures, stagnation cycles, scope additions, and per-task attempts.
- A canonical JSON task graph now owns task status and evidence; the Markdown view is generated from it.
- `COMPLETE` now fails closed for stale mandatory tasks, missing task evidence, missing live implementation/verification activity, untouched tool-call budget, or no observable workspace change during implementation.
- Installer-managed Skill changes now leave a versioned restart-pending marker outside the Skill directory. The on-disk fallback refuses StackMarshal invocation until a matching newly loaded Skill acknowledges the marker, while `stackmarshal doctor --host-skill-version` also detects Skill/CLI/host-session mismatch.

## Evidence

The candidate passed the existing unit/integration/security suite, strict mypy, Ruff, the 85% coverage gate, wheel/sdist build, Twine checks, and a dedicated fresh nested-workspace experiment reproducing the original Phase 3B failure shape.

See `docs/NEXTPATCH_EXPERIMENT_REPORT.md` for the experiment design and evidence.

## Compatibility note

The v1 Codex adapter still does not intercept every native host tool call. The live `tool_calls` ledger is therefore an observable Core-owned reservation/recording mechanism used by the Skill around bounded host-tool batches; it is not presented as host-level instrumentation.

## Release gate

The deterministic release asset build must be rerun after the candidate is locally committed so the Git-tracked source archive includes every v1.1.1 file. Do not publish before that post-commit verification passes.
