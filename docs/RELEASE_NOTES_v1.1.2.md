# StackMarshal v1.1.2

StackMarshal v1.1.2 is a release and terminal integrity hardening patch. It is derived from the
v1.1.1 clean-room dogfood, the post-release CI version-drift incident, and the operational lessons
from the v1.1.0 -> v1.1.1 patch cycle.

## What changed

- `pyproject.toml [project].version` is now the release-version authority. A dedicated version
  contract checks Core, Skill, installer-smoke resolution, Skill readiness commands, and living
  README examples. `--sync` updates only current-version mirrors and deliberately leaves historical
  release evidence untouched.
- CI and the deterministic release builder fail closed when the version contract drifts.
- A staged `scripts/release_gate.py` provides candidate, immutable, and published-asset verification
  entry points with machine-readable and Markdown evidence. Immutable bootstrap smoke is mandatory.
- Published-bundle verification rejects checksum path traversal, symlinks, duplicate or incomplete
  asset sets, manifest metadata drift, dirty provenance, component version skew, and manifest/provenance
  Git HEAD values that do not bind to the expected immutable commit. Immutable release builds also
  reject hidden/nonstandard Git index flags (`assume-unchanged` / `skip-worktree`) and ignored files
  that could contaminate package or Skill artifacts despite an apparently clean worktree.
- Workspace-state reads and writes fail closed on symlink/junction escapes for `.stackmarshal`, its
  project/run state, known generated evidence files, and `.gitignore` initialization. This closes the
  same workspace-escape class at initialization/runtime state boundaries, not only at finalization.
- Git command classification now rejects execution-capable/read-escape options such as `--ext-diff`,
  `--textconv`, `--open-files-in-pager`, `--output`, and `--no-index`, rejects Git global-option
  injection, and requires approval for unknown subcommands that may resolve to aliases.
- Repository configuration may tighten bounded budgets but cannot expand them, select the `deep`
  profile, disable mandatory approvals, or weaken guarded autonomy. `--budget deep` remains an
  explicit user CLI choice rather than a repository-controlled policy escalation.
- Release manifests now carry explicit component version-coherence evidence.
- Build-mode runs must execute `stackmarshal finalize` during VERIFICATION before COMPLETE.
  Unsafe managed-state paths encountered during finalization are normalized to `INVALID_STATE`
  consistently across Windows, Linux, and macOS instead of being misclassified as invalid input.
  The final verification activity records a terminal deliverable fingerprint; finalization refuses
  source/build/dist/release changes after that evidence boundary, regenerates the task view and
  environment audit, and seals the complete `.stackmarshal/project/` evidence tree plus the verified
  deliverable fingerprint.
- Git-only housekeeping may occur after finalization and before COMPLETE. COMPLETE then validates
  that sealed content did not change and records a non-mutating terminal repository seal containing
  Git HEAD, dirty paths/status, and the final workspace fingerprint.
- Restricted hosts may run `scripts/smoke_installer.py --direct-installer` to diagnose the shared
  installer path when PowerShell/Bash process creation is unavailable; this does not replace the
  mandatory platform-bootstrap smoke in the immutable release gate.
- Version synchronization, release-gate report writes, and release build-output cleanup reject
  symlink/junction targets. `build`, `dist`, and `release` are validated as repository-local regular
  directories before deletion or reuse, and finalization validates the full state boundary before
  regenerating any evidence.
- The v1.1.1 nested-workspace dogfood scenario is promoted from a one-off Nextpatch experiment to
  `tests/test_live_orchestration_contract.py`, a permanent regression contract.
- The living future-work document now matches the `AGENTS.md` contract at `docs/FUTURE_WORK.md`, and
  the release checklist no longer embeds stale release-specific test/coverage/version facts.

## Scope

v1.1.2 intentionally does not add new agent adapters or multi-agent orchestration. Those remain
feature-release work for v1.2.0 or later.

## Release contract

Before publication, the candidate must pass the repository quality gates, Codex Security review,
an immutable clean-worktree release gate, deterministic release build, checksum/manifest checks,
and the platform installer smoke appropriate to the release environment. Published assets remain
immutable; v1.1.2 does not rewrite or replace v1.1.1 release assets.
