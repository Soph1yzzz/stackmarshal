# StackMarshal v1.1.5

StackMarshal v1.1.5 is a dogfood-driven recovery-hardening release. The core finding from real OSS use was simple: StackMarshal was already good at refusing false `COMPLETE`, but a correctly stopped run was harder to continue than it should have been. This release closes that gap and fixes the adjacent state/CLI issues exposed by the same field use.

## Resume is now real

A signed checkpoint is no longer inspection-only. For resumable terminal states, use:

```text
stackmarshal resume <run-id>
```

Before reopening the same run id, StackMarshal verifies the checkpoint HMAC, project identity, Git HEAD/dirty state, exact worktree fingerprint, and the signed resume phase. `CHECKPOINT_READY`, `BLOCKED_EXTERNAL`, `VERIFICATION_EXTERNAL_BLOCKED`, and `APPROVAL_REQUIRED` are resumable. Unsafe, exhausted, stagnated, repeated-failure, scope-drift, invalid, cancelled, and complete runs remain terminal.

Checkpoint creation records the phase to resume and emits the exact resume command. Successful explicit checkpoint creation now exits successfully and states that the terminal checkpoint was created; a successful checkpoint is no longer easy to mistake for checkpoint-generation failure.

## Legacy unsigned state migration

v1.1.3 made live run/task authority HMAC-authenticated. Repositories carrying older unsigned `.stackmarshal` state could therefore fail closed before a new run could start. v1.1.5 adds:

```text
stackmarshal migrate
stackmarshal migrate --dry-run
```

Migration does **not** sign old state and pretend it is trusted. Unsigned legacy run/task evidence is moved under the already-ignored StackMarshal runtime boundary into a read-only archive with a SHA-256 manifest. Partial or unknown integrity envelopes are not treated as legacy and remain fail-closed. After archival, a new signed run can start normally.

## Bounded verification correction

Small fixes discovered by verification no longer consume architecture replans:

```text
VERIFICATION
    -> CORRECTION
    -> VERIFICATION
```

`CORRECTION` supports correction activity and task attempts/completion while leaving the architecture-replan counter untouched. `REPLAN` remains reserved for architecture/task-plan changes.

## External verification and blocker propagation

`VERIFICATION_EXTERNAL_BLOCKED` is now a first-class formal stop for network/service-dependent gates such as an audit command timing out. It is distinct from code failure and from generic stagnation and can resume after the external blocker is resolved.

When a mandatory task is blocked with a reason beginning `BLOCKED_EXTERNAL:` or `VERIFICATION_EXTERNAL_BLOCKED:`, the reason is propagated into run-level stop evidence. A subsequent checkpoint therefore carries the real blocker instead of `Stop reason: None`.

## Windows UTF-8 evidence

The CLI now reconfigures stdout/stderr to UTF-8 when the host stream supports it. Python already receives Windows argv as Unicode; this closes the output-side legacy code-page boundary so Japanese invocation text and JSON evidence remain UTF-8 instead of becoming mojibake.

## Less invasive init

`stackmarshal init` now asks Git whether `.stackmarshal/runs/` is already ignored before editing the project `.gitignore`. Existing `.git/info/exclude`, global exclude, or project ignore coverage prevents redundant repository mutation. Full repository-external/non-invasive state placement remains v1.1.6 work.

## Shadowed launcher repair

v1.1.4 made shadowed old StackMarshal launchers visible without falsely blocking a healthy managed launcher. v1.1.5 adds an explicit repair path:

```text
stackmarshal repair
stackmarshal repair --remove-shadowed
```

The first command re-runs the current managed pin through the verified atomic installer. `--remove-shadowed` additionally removes only non-managed PATH launchers with high-confidence StackMarshal package/version evidence; unknown executables are left untouched and reported instead of being deleted.

## Additional checkpoint safety

For workspaces that are not their own Git repository, checkpoint worktree identity now falls back to StackMarshal's workspace fingerprint instead of `None`. A file changed after checkpoint creation therefore invalidates resume in non-Git workspaces as well.

## Scope discipline

The previously planned delivery-quality audit and compact human output remain useful, but they move unchanged to v1.1.6. This release stays focused on issues directly demonstrated by field use: truthful stopping, truthful recovery, state compatibility, bounded correction, and operator-facing evidence correctness.
