# HostWriteAdapter protocol

StackMarshal keeps one state machine and changes only the transport used to write project evidence.
Normal Codex/CLI runs use direct filesystem writes. Hosts that forbid shell-originated project writes,
such as DevSpace, consume a signed HostWrite plan through their native file API.

## Authority boundary

StackMarshal Core decides the mutation, expected preimage, required postimage and plan identity. A host
adapter is only a transport. It must not invent state transitions, alter an operation, acknowledge a
partial transaction, or treat a host-side success response as proof of the final project state.

A plan remains pending until `host-write ack` recomputes every signed postimage hash. While that plan
exists, StackMarshal rejects every project-mutating command in both `host` and `direct` write modes.
The pending record itself is created with an exclusive filesystem create, so another process cannot
replace the slot after merely winning a check/write race.

## Operation types

### `write_text`

For an existing file, the plan contains the exact expected UTF-8 preimage and its SHA-256. Prefer a
host primitive that replaces that exact preimage. For a new file, the signed preimage is absent and
the adapter must confirm that the target is absent before creating it.

### `append_text`

Append operations are intended for growing evidence such as `events.jsonl`. The plan carries:

- the expected whole-file SHA-256 and byte size;
- at most 512 characters of signed `expected_tail` for hosts with exact text-edit primitives;
- only the new `append_content` and its SHA-256;
- the required whole-file postimage SHA-256.

The previous full file is not inlined into the plan. StackMarshal stores a content-addressed recovery
copy in the user state directory. `host-write recover` can surface that signed preimage if recovery is
needed.

A host with an atomic append/CAS primitive should check the full preimage SHA and append directly. A
host such as DevSpace can normally use `expected_tail` as the exact `oldText` and
`expected_tail + append_content` as `newText`. If that tail is not unique or the native edit cannot
provide the required guard, run `host-write check` and use the recovery preimage rather than silently
weakening the contract.

## DevSpace flow

The StackMarshal Skill treats DevSpace as a first-class shell-write-restricted host:

```text
stackmarshal --write-mode host <mutation>
        ↓
optional host-write check (required when native CAS is insufficient)
        ↓
DevSpace write/edit applies the signed operations
        ↓
stackmarshal host-write ack --plan-id <id>
```

Apply all independent operations from the same plan before ACK. Do not issue another StackMarshal
mutation between them. Current DevSpace file tools operate per file, so StackMarshal does not claim
multi-file atomicity that the host does not provide. If a future DevSpace API exposes a transactional
batch, a `HostWriteAdapter` may consume the same signed plan in one host operation without changing
Core semantics.

## Recovery

If a project file changes before ACK, leave the plan pending and inspect it first:

```text
stackmarshal host-write status
stackmarshal host-write check --plan-id <id>
stackmarshal host-write recover --plan-id <id> [--path <relative-path>]
```

`recover` does not write the project. It returns only preimages derived from the already verified
signed plan or its content-addressed recovery blob. Restore them through the host's native file API,
then rerun `check` and apply the original plan. If the original preimage was absence, the recovery
record says `expected_absent=true`; the host must use a native delete/remove capability if a file was
created accidentally.

## Workspace relocation

Relocation is separate from Git repository bootstrap. Before moving an active workspace, create a
signed permit:

```text
stackmarshal relocate prepare --to <new-root> --run-id <id>
```

Move the workspace without changing its contents, then from the destination run:

```text
stackmarshal --write-mode host relocate accept --permit-id <id> --run-id <run-id>
```

(or omit `--write-mode host` on a normal direct-write host).

Acceptance requires the signed deliverable fingerprint, portable repository identity, Git HEAD and
dirty state to match the pre-move permit. The resulting identity event is `workspace_relocation`.
If Git is initialized later, that remains a distinct `workspace_repository_bootstrap` migration.
