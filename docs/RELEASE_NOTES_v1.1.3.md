# StackMarshal v1.1.3

StackMarshal v1.1.3 is a runtime-trust hardening patch derived from real OSS field use during
MandateMarshal v0.2 durable-runtime and crash-recovery development. It intentionally does not add
new adapters, orchestration modes, or operator-UX features.

The release focuses on three places where StackMarshal's own execution/evidence path must be
trustworthy: terminal Git status parsing, installation/launcher version provenance, and Windows
workspace fingerprint diagnostics.

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

v1.1.3 does not change the StackMarshal state schema, checkpoint schema, task-graph schema, mode
model, approval boundary, or release-asset format. Existing v1.1.x state/evidence contracts remain
in place. The patch changes diagnostics and corrects terminal path evidence without weakening any
completion or fingerprint gate.
