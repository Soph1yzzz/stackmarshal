# StackMarshal v1.2.2

v1.2.2 makes the harness more informative without making it more prescriptive.

## `stackmarshal next`

`stackmarshal next` is read-only introspection. It reports the current run state, blockers, legal phase transitions, incomplete mandatory tasks, completion prerequisites, and HostWrite status.

It does not choose a recovery command. Diagnostic failures such as workspace fingerprint errors are returned as blockers instead of hiding the underlying cause.

## Bounded late-task admission

Mandatory work discovered after `TASK_GRAPH` can now be added from `REPLAN` with `task add --replan`.

The admission consumes both architecture-replan and scope-addition budget. Normal task addition outside `TASK_GRAPH` remains rejected.

## Host-observed telemetry

`activity sync-host` accepts a monotonic tool-call total from a named host source. Replaying the same total is a no-op; only the positive delta is charged to the run budget. A counter moving backwards is rejected.

Manual `activity record tool-call` remains available when the host has no measured counter.

## Readiness split

`doctor` now distinguishes Core readiness from Codex Skill/session readiness. Core health no longer becomes a repair failure merely because Codex still needs to reload its Skill. `doctor --host-skill-version` remains strict for Codex integration checks.

## Invocation parity

Short Japanese mechanism requests such as `StackMarshalで次のvを作ろう` now trigger consistently in both the packaged Core and the dependency-free Skill fallback. Topic-only mentions remain non-triggers.

## Verification

- Full test suite on Python 3.11
- Ruff
- strict mypy
- branch coverage gate
- package/Twine checks
- adversarial regression
- focused source review
- CI and CodeQL
