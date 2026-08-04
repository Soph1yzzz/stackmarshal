# Forward Test Report

Date: 2026-08-04

## Automated host-independent coverage

- Explicit Japanese, English, Simplified Chinese, and `$stackmarshal` invocation.
- Anti-trigger cases for explanation, comparison, README editing, and ordinary implementation.
- research, prepare, build, and resume mode inference.
- Full CLI lifecycle: init, start, audit, transitions, budget, score, fingerprint, progress,
  lock, checkpoint, resume, validation, formal stop, and report.
- Budget exhaustion, invalid transition, repeated-state protection, unsafe lock, malformed JSON,
  strict run IDs, workspace escape, install hooks, secret redaction, and receipt-bound rollback.
- Git HEAD, dirty-state, exact tracked/staged/untracked fingerprint, repository-lineage identity, HMAC checkpoint integrity, and future-schema rejection.
- Direct Skill fallback execution without runtime package dependencies.
- Installed CLI wrapper execution with an explicit external `--root`.
- JSON Schema meta-validation and runtime example validation.

## Platforms

Local release validation ran on Windows 11 with Python 3.11. The GitHub Actions matrix covers
Ubuntu, macOS, and Windows with Python 3.11, 3.12, and 3.13. Public CI results are recorded in
the final release checklist after repository publication.

## Adversarial cases

The suite covers malicious install hooks, download-to-shell patterns, PowerShell dynamic
execution, secret-access commands, public/network/global/privileged writes, unpinned and
unlicensed candidates, artifact hash mismatch, workspace traversal, checkpoint tampering,
release symlink exfiltration, command-classification bypasses, forged rollback receipts,
and external text that does not satisfy the explicit invocation gate.

## Result

45 tests were collected after Codex Security remediation, reverse hardening, and portable
release-metadata checks. Windows ran 44 passes with the POSIX-symlink case skipped by
operating-system privilege; the identical symlink rejection path was executed successfully
under WSL/Linux. Branch-aware coverage is 94%.
