# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and Semantic Versioning.

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
