# StackMarshal v1.1 Acceptance Report

## Invocation

- PASS: explicit Japanese, English, Simplified Chinese, and `$stackmarshal` triggers.
- PASS: ordinary implementation, explanation, comparison, and README-edit anti-triggers.

## Workflow

- PASS: requirements/acceptance contract in the Skill and traceability matrix.
- PASS: bounded research gate and evidence bundle.
- PASS: capability categories for Skill, MCP, plugin, library, CLI, and reference OSS.
- PASS: weighted candidate scoring, hard disqualifiers, provenance/lock format.
- PASS: architecture-freeze, task-graph, implementation, verification, and formal-stop policies.

## Safety

- PASS: external repository text is explicitly untrusted.
- PASS: install hooks and download-to-shell patterns are detected.
- PASS: global, network, secret, billing, publication, privileged, interpreter, unknown, and destructive actions require approval unless explicitly proven safe.
- PASS: unpinned, unlicensed, excessive-permission, and unreviewable candidates are rejected.
- PASS: workspace escape, run-id traversal, release symlinks, secret logging, self-recursion, and runtime self-modification are prohibited.
- PASS: HMAC-signed acquisition receipts, installed-file hashes, exact-file rollback, replacement detection, and recursive-deletion rejection are implemented and tested.

## Installation and update

- PASS: Windows PowerShell and macOS/Linux Bash one-command bootstraps install the CLI and matching Codex Skill.
- PASS: Git, Python 3.11+, and Python venv support are detected before acquisition.
- PASS: missing prerequisite installation, PATH changes, modified Skill replacement, and downgrade require explicit approval unless deliberate non-interactive approval is supplied.
- PASS: latest stable discovery and explicit semantic-version pinning are supported.
- PASS: shared installer, wheel, and Skill archive are verified against strict Release checksums.
- PASS: CLI installation is isolated in a dedicated venv and uses no package index or transitive dependency resolution.
- PASS: Skill extraction rejects traversal, duplicate, symlink, backslash, and non-regular entries.
- PASS: staged atomic swaps, launcher/state snapshots, pre-commit rollback, modified Skill backup, and staging cleanup are implemented and tested.
- PASS: install, update, same-version repair, CLI-only, Skill-only, no-PATH, and explicit downgrade modes are represented.
- PASS: post-install doctor verifies CLI version, Skill hash, state, and cleanup.

## Stop harness and resume

- PASS: research, candidate, tool, replan, task-attempt, failure, stagnation, and scope budgets.
- PASS: safety-first stop priority and terminal status codes.
- PASS: every formal CLI stop creates checkpoint JSON and Markdown.
- PASS: user-local HMAC checkpoint integrity, repository-lineage identity, exact worktree fingerprint, Git HEAD, dirty state, completed work, and do-not-repeat state.
- PASS: unknown future state/checkpoint schemas are rejected.

## Distribution and quality

- PASS: installable `skills/stackmarshal/` folder and dependency-free fallback.
- PASS: Python package and `stackmarshal` executable with zero runtime dependencies.
- PASS: English primary README and Japanese secondary README.
- PASS: Apache-2.0, SECURITY, CONTRIBUTING, Code of Conduct, RFC process, issue/PR templates.
- PASS: 61 collected tests, Ruff, mypy strict, 94% branch-aware Core coverage, build, Twine validation, and portable checksum verification.
- PASS: Linux/macOS/Windows CI matrix and commit-pinned CodeQL workflow.
- PASS: reproducible Skill/source archives, wheel/sdist, bootstrap assets, SHA256SUMS, SBOM, provenance, and release manifest.
- PASS: CI builds and smoke-tests the one-command installer on every supported operating system.

## Final publication gates

The release is marked COMPLETE only after the immutable release commit passes the final Codex
Security repository scan, public CI and CodeQL succeed, the v1.1.0 tag resolves to that commit,
all published asset digests match the local deterministic build, downloaded `SHA256SUMS` verify,
and a clean public installer smoke succeeds.
