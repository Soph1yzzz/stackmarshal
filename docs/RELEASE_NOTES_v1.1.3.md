# StackMarshal v1.1.3

StackMarshal v1.1.3 is a runtime-trust hardening patch derived from real OSS field use during
MandateMarshal v0.2 durable-runtime and crash-recovery development. It intentionally does not add
new adapters, orchestration modes, or operator-UX features.

The release focuses on four places where StackMarshal's own execution/evidence path must be
trustworthy: terminal Git status parsing, installation/launcher version provenance, Windows
workspace fingerprint diagnostics, and authenticated live run/task authority.

## Fixed

### Terminal seal preserves Git porcelain status columns

`git status --porcelain` uses leading whitespace as structural status columns. Previous code passed
that output through a generic `.strip()` before extracting `entry[3:]`, which could shift the path
column and record a dirty path such as `AGENTS.md` as `GENTS.md`.

v1.1.3 removes only subprocess line terminators from Git text output, preserving porcelain-leading
status bytes. Regression coverage now verifies that a modified `AGENTS.md` is sealed exactly as
`AGENTS.md` with the original porcelain status line intact.

### `doctor` surfaces StackMarshal version skew and launcher provenance

A field environment contained multiple StackMarshal execution paths at once: a managed launcher,
another Python `Scripts` launcher, installed package metadata, and a loaded Codex Skill could refer
to different versions.

v1.1.3 expands `stackmarshal doctor` to report:

- the CLI version and invocation entrypoint currently running,
- the installed Codex Skill version and host Skill version,
- managed install root, recorded managed version, and managed launcher,
- the command currently resolved by PATH,
- all StackMarshal launcher candidates found on PATH,
- high-confidence launcher version evidence and nearby distribution metadata versions,
- an explicit `version_skew` result, known versions, warnings, and repair requirement.

Doctor deliberately does **not** execute arbitrary sibling PATH candidates merely to ask their
version. It derives provenance from managed installer state, bounded launcher inspection, the
current invocation, and nearby package metadata so the diagnostic itself does not expand the
trusted-execution boundary.

### Windows reserved device names receive an explicit fingerprint diagnostic

A Windows workspace containing a local artifact named `NUL` previously failed fingerprinting with
a generic "entry changed" style error. The actual cause is Windows reserved device-name semantics.

v1.1.3 detects reserved path components before resolve/read operations:

- `CON`, `PRN`, `AUX`, `NUL`
- `COM1` through `COM9`
- `LPT1` through `LPT9`
- the same reserved stems when followed by an extension or Windows-trimmed trailing dot/space

The fingerprint remains fail-closed. Reserved-name entries are not silently omitted from terminal
evidence.

### Live run and task authority is HMAC-authenticated

A risk-triggered pre-release security review identified a trust asymmetry: checkpoints and
acquisition receipts were protected by the user-local integrity key, but canonical live `run.json`
and `task-graph.json` could still be accepted after repository-local modification. In a repository
that already contained forged StackMarshal state, that could influence active-run selection,
phase/progress authority, mandatory task evidence, finalization, and the path toward `COMPLETE`.

v1.1.3 now signs live run state and canonical task state with the same user-local
`hmac-sha256-v1` integrity boundary and verifies the signature before accepting either file as
authority. Unsigned or modified canonical state fails closed. Regression tests cover forged live
phase/completion state, forged task completion/evidence, and unsigned repository-supplied state.
The shared signing key remains outside the repository.

## Security review outcome

A full Codex Security Standard scan was attempted because v1.1.3 touches runtime trust. Scan
`8c22f190-b4ca-4d35-9b08-c287ea3f2657` reached validation coverage of 122 / 122 tracked files on
commit `3abd8433009c020417695b1c12612c673ca70902` and surfaced the live-authority issue above. The
headless SDK session then stalled before writing/sealing canonical scan artifacts, so it is **not**
claimed as a passing final full scan and was stopped rather than consuming Sol usage indefinitely.
The remediated candidate is gated by focused source-backed security review, targeted adversarial
regressions, CI, and CodeQL under the project's risk-triggered scan policy.

## Field evidence

[Case Study #2 — MandateMarshal v0.2](CASE_STUDY_02_MANDATEMARSHAL.md) records the field run that
drove this patch. The most important positive result was independent of the defects above: after a
late source change, StackMarshal rejected `COMPLETE` with
`missing_verified_workspace_fingerprint` until verification was repeated against the final
workspace.

The case study also preserves a narrower evidence correction: a report that one observed 1.1.1
execution path lacked `task complete --evidence` was not reproduced against the official v1.1.1
source/parser. The release therefore treats that observation as execution-path/version ambiguity,
not as an official v1.1.1 parser defect.

## Deferred to v1.1.4

The following field-review improvements are intentionally excluded from v1.1.3 so this patch stays
focused on runtime/evidence trust:

- non-invasive/local initialization that does not mutate the target repository `.gitignore`,
- a delivery audit spanning task evidence, verification freshness, changed files, unresolved
  failures, and finalize readiness,
- compact human CLI output with explicit full JSON mode.

See [FUTURE_WORK.md](FUTURE_WORK.md) for the version roadmap.

## Compatibility

v1.1.3 does not bump the public run-state or task-graph schema version, mode model, approval
boundary, checkpoint schema, or release-asset format. Generated live `run.json` and
`task-graph.json` now include an additive integrity envelope, and runtime trust is intentionally
stricter: unsigned legacy live state/task state is not accepted as canonical execution authority.
Users with an in-progress pre-v1.1.3 run should preserve its signed checkpoint evidence and start
or reconstruct trusted live state rather than blindly blessing an unsigned repository copy. This
security hardening does not weaken any completion or fingerprint gate.
