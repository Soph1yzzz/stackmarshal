# Case Study #2 — MandateMarshal v0.2 durable runtime and crash recovery

## Summary

StackMarshal was used during real OSS development of MandateMarshal v0.2, specifically the durable-runtime and crash-recovery work. Unlike Case Study #1, which was a controlled Phase 3B dogfood, this was a field-use report from a separate Sol session performing a substantive implementation task.

The run used build mode with the standard budget and reached StackMarshal `COMPLETE` only after the completion gate and finalization contract passed.

Reported run metrics:

- research rounds: **1**
- tool calls: **72**
- mandatory tasks: **5**
- task attempts: **5**
- attempts per task: **1**
- terminal state: **`COMPLETE`**

The main product finding was positive: StackMarshal changed a long agent session from an implicit conversation into an explicit run with externally recorded phase, task, budget, verification, and finalization state.

## What the run demonstrated

### Explicit phase boundaries remained useful during real implementation

The run moved through the expected bounded workflow:

`RESEARCH -> ARCHITECTURE_FREEZE -> TASK_GRAPH -> IMPLEMENTATION -> VERIFICATION`

The field report specifically found the phase boundaries useful for preventing two common failure modes: research continuing indefinitely, and implementation beginning before the architecture had stabilized.

### Task evidence fit crash-recovery work well

The implementation was divided into five tasks. All five completed in one attempt, with acceptance criteria and evidence recorded per task. The operator reported that this worked well for crash-recovery development because additional boundary conditions could be discovered during implementation without losing the explicit task/evidence contract.

### The completion gate prevented a real verification-freshness mistake

After VERIFICATION, an additional source change was made and the run attempted to advance to `COMPLETE` without re-verifying the final workspace.

StackMarshal rejected the transition with:

```text
missing_verified_workspace_fingerprint
```

The final state therefore could not claim completion until verification was repeated against the changed workspace. This is the strongest result in the case study: the completion gate did not merely record activity; it changed the outcome by preventing stale verification evidence from authorizing `COMPLETE`.

### Finalization produced a useful terminal record

The final report collected the run ID, mode, phase/status, budget usage, phase fingerprints, verification fingerprint, finalization hashes, and terminal seal in one place. The operator found this substantially easier to inspect after the fact than reconstructing a long development session from chat history.

## Issues discovered by field use

The field run also exposed concrete StackMarshal defects and UX gaps.

### 1. Terminal-seal Git porcelain parsing could corrupt a dirty path

The report observed `AGENTS.md` recorded as `GENTS.md` in terminal-seal dirty paths.

Source inspection confirmed the cause in `state.py`: `_run_git()` applied a generic `.strip()` to `git status --porcelain` output, while the terminal snapshot parser later used `entry[3:]`. Git porcelain leading whitespace is structural status data, so removing it first shifts the path column and can drop the first filename character.

This is a confirmed StackMarshal bug and a v1.1.3 hardening item.

### 2. Multiple StackMarshal installation paths created version ambiguity

The field report found different StackMarshal versions through different local launch paths. Follow-up inspection on the development machine reproduced the broader condition: a managed launcher, a separate Python `Scripts` launcher, installed package metadata, and the loaded Skill could represent different versions simultaneously.

The original field report also stated that one observed 1.1.1 execution path rejected `task complete --evidence`. Follow-up against the official v1.1.1 source and the currently managed v1.1.1 launcher did **not** reproduce the claim that v1.1.1 itself lacks the `--evidence` argument; the official parser contains it. The finding is therefore recorded more narrowly as execution-path/version ambiguity rather than as an official v1.1.1 parser defect.

This distinction matters: the verified problem is that an operator or agent can execute a stale or alternate StackMarshal path without sufficiently strong provenance diagnostics.

v1.1.3 therefore strengthens `doctor` to report the invoked CLI, installed Skill, managed install state, PATH resolution, multiple StackMarshal launcher candidates, and non-executing version evidence. Doctor does not execute arbitrary sibling PATH candidates merely to identify them.

### 3. Windows reserved device names produced misleading fingerprint failure

The workspace contained an ignored zero-byte artifact named `NUL`. Workspace fingerprinting failed with a generic message equivalent to an entry changing during fingerprinting. Removing the artifact allowed verification to continue.

The problem is Windows-specific naming semantics rather than ordinary file mutation. v1.1.3 detects reserved Windows device components (`CON`, `PRN`, `AUX`, `NUL`, `COM1..9`, `LPT1..9`) before resolving/reading them and reports the actual cause.

The fingerprint remains fail-closed. StackMarshal does not silently exclude a reserved-name entry, because doing so could make terminal evidence omit workspace content.

### 4. `init` mutates the target repository's `.gitignore`

`stackmarshal init` currently adds StackMarshal run-state patterns to the project `.gitignore`. This is deliberate today, but field use showed a valid operator preference for keeping orchestrator bookkeeping from dirtying the target repository.

This is deferred to v1.1.4 as a local/non-invasive initialization mode, potentially using `.git/info/exclude` or repository-external state.

### 5. `audit` is an environment inventory, not a delivery audit

The current `stackmarshal audit` writes environment and native-capability inventory. The field report expected a final cross-check of changed files, task acceptance/evidence, verification freshness, unresolved failures, and finalize readiness.

That broader delivery review is deferred to v1.1.4. The existing environment audit remains useful and should be named/scoped more explicitly rather than overloaded silently.

### 6. Human CLI output is verbose

Phase transitions currently print the full run JSON. This is strong machine output but noisy for interactive terminal operation. A compact human default with explicit full JSON output is deferred to v1.1.4.

## v1.1.3 response

Case Study #2 directly defines the v1.1.3 runtime-trust hardening scope:

1. preserve Git porcelain status columns and fix terminal dirty-path parsing,
2. detect launcher / CLI / Skill / managed-install version skew in `doctor`,
3. diagnose Windows reserved device names explicitly during workspace fingerprinting while preserving fail-closed evidence semantics.

The non-invasive-init, delivery-audit, and compact-output work is intentionally separated into v1.1.4 so the v1.1.3 patch remains focused on trustworthiness of execution and evidence.

## Evidence provenance and limitations

This document is a field-use record, not a claim that the MandateMarshal repository or raw StackMarshal run directory is archived in this repository.

The reported run metrics and workflow observations come from the Sol session that performed the MandateMarshal v0.2 work. StackMarshal source follow-up in this repository independently confirmed the porcelain parsing bug, the current environment-only scope of `audit`, and the `.gitignore` mutation performed by `init`. Local environment follow-up also reproduced multi-version StackMarshal installation ambiguity.

Where follow-up did not reproduce a narrower claim — specifically that official v1.1.1 lacked `task complete --evidence` — this case study records the narrower verified conclusion instead of preserving the stronger claim as fact.

That limitation is intentional. The purpose of the case study is to retain what field use actually taught the project, including both successful gates and defects discovered under use.
