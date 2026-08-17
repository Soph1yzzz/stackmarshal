# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and Semantic Versioning.

## [Unreleased]

### Added

- v1.1.2 release-version contract with `pyproject.toml` as authority and fail-closed Core/Skill/docs coherence checks.
- Staged candidate/immutable/published release gate with machine-readable evidence.
- Explicit VERIFICATION finalization and non-mutating terminal repository seal before COMPLETE.
- Permanent nested-workspace live-orchestration E2E regression contract.

### Changed

- Release manifests include component version-coherence evidence.
- Living release checklist uses stable gate requirements instead of stale release-specific counts.
- Future work now lives at the repository-contract path `docs/FUTURE_WORK.md`.

## [1.1.1] - 2026-08-16

### Added

- One authoritative live run across nested-repository bootstrap and first-commit lineage migration.
- Core-owned live activity/budget accounting and canonical task graph with evidence-gated COMPLETE.
- Versioned restart-pending marker and stale-host readiness refusal after Skill update.

### Changed

- Live phase snapshots distinguish real orchestration from retrospective transition replay.
- COMPLETE fails closed on stale mandatory tasks, missing live activity, untouched tool budgets, and missing implementation change evidence.

## [1.1.0] - 2026-08-05

### Added

- One-command Windows PowerShell and macOS/Linux Bash installation for the CLI and matching Codex Skill.
- Stable-version discovery, explicit version pinning, same-version repair, update, and guarded downgrade flows.
- Explicit approval before installing missing Git, Python, or venv support and before changing PATH or replacing a modified Skill.
- Dedicated managed virtual environments, strict Release checksum verification, safe Skill ZIP extraction, atomic directory swaps, rollback, modified-Skill backup, and post-install doctor checks.
- Cross-platform installer smoke tests and fresh-install audit evidence.

### Changed

- Release assets now include `install.ps1`, `install.sh`, and the shared `installer.py`.
- The recommended installation path no longer writes into the active or global Python environment.
- Skill and CLI release versions are synchronized and recorded in installer state.

## [1.0.0] - 2026-08-04

### Added

- Explicit multilingual StackMarshal invocation gate and mode inference.
- Deterministic state machine, event log, budgets, progress evaluation, and stop harness.
- Candidate scoring, supply-chain inspection, lock verification, acquisition receipts, and rollback.
- User-local HMAC-signed checkpoints and acquisition receipts, repository-lineage identity, exact worktree fingerprints, and resume inspection.
- Agent-neutral Core with the initial Codex adapter.
- Installable Codex Skill with bounded fallback scripts.
- Cross-platform CLI, JSON Schemas, 94% branch-aware test coverage, and adversarial tests.
- English primary README and Japanese secondary README.
- Reproducible release assets, symlink rejection, portable LF SHA-256 checksums, SBOM, and provenance metadata.
- Linux, macOS, Windows CI and CodeQL workflows with commit-pinned Actions.
- Fail-closed command approval, strict run IDs, signing-key isolation, and hash-verified receipt-bound non-recursive rollback.
