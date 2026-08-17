# v1.1.0 Forward Test Report (Historical Evidence)

Date: 2026-08-05

This document is immutable historical evidence for the v1.1.0 release line. Current release
requirements and thresholds live in `docs/RELEASE_CHECKLIST.md`.

## Automated host-independent coverage

- Explicit Japanese, English, Simplified Chinese, and `$stackmarshal` invocation.
- Anti-trigger cases for explanation, comparison, README editing, and ordinary implementation.
- research, prepare, build, and resume mode inference.
- Full CLI lifecycle: init, start, audit, transitions, budget, score, fingerprint, progress,
  lock, checkpoint, resume, validation, formal stop, and report.
- Budget exhaustion, invalid transition, repeated-state protection, unsafe lock, malformed JSON,
  strict run IDs, workspace escape, install hooks, secret redaction, and receipt-bound rollback.
- Git HEAD, dirty-state, exact tracked/staged/untracked fingerprint, repository-lineage identity,
  HMAC checkpoint integrity, and future-schema rejection.
- Direct Skill fallback execution without runtime package dependencies.
- Installed CLI wrapper execution with an explicit external `--root`.
- JSON Schema meta-validation and runtime example validation.
- Strict installer version/checksum parsing, checksum-failure cleanup, downgrade refusal, safe Skill
  ZIP extraction, atomic directory rollback/finalization, and bootstrap prerequisite contracts.

## Installation experiments

Local Release fixtures were served over loopback connections and every install target was placed
under ignored `.stackmarshal/runs/installer-lab-*` directories.

- Windows PowerShell fresh install passed with a dedicated venv, matching Skill, launcher,
  persisted hashes/state, no-PATH mode, and doctor verification.
- Windows same-version repair passed.
- Ubuntu/WSL reproduced the Debian split-package case where Python existed but venv support did
  not. The bootstrap detected and repaired that prerequisite after approval.
- Ubuntu/WSL normal-user fresh install passed after prerequisite repair.
- Ubuntu/WSL repair of a locally modified Skill preserved the change in backup and restored the
  active verified Skill.
- Experiment-only Windows Python 3.13 and WSL venv packages were removed after testing. Existing
  Python security updates applied by the package manager were retained instead of downgraded.

See `docs/INSTALLATION_AUDIT.md` for the full boundary and cleanup record.

## Platforms

Local release validation ran on Windows 11 with Python 3.11 and Ubuntu under WSL with Python
3.12. GitHub Actions covers Ubuntu, macOS, and Windows with Python 3.11, 3.12, and 3.13. The
Python 3.11 job on each operating system also builds the complete v1.1.0 Release and runs a fresh
bootstrap smoke test against a temporary local Release endpoint.

## Adversarial cases

The suite covers malicious install hooks, download-to-shell patterns, PowerShell dynamic
execution, secret-access commands, public/network/global/privileged writes, unpinned and
unlicensed candidates, artifact hash mismatch, workspace traversal, checkpoint tampering,
release symlink exfiltration, installer archive traversal/symlinks, malformed/duplicate
checksums, command-classification bypasses, forged rollback receipts, guarded downgrade, and
external text that does not satisfy the explicit invocation gate.

## Result

61 tests were collected after installer implementation and hardening. Windows ran 59 passes with
two POSIX-symlink cases skipped because the local account lacks symlink privilege; corresponding
symlink rejection paths are executed under Linux. Branch-aware Core coverage is 94%.
