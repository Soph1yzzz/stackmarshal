# StackMarshal v1.2.1

StackMarshal v1.2.1 is the HostWrite ergonomics and transaction-hardening release. It keeps the v1.2.0 authority model intact and addresses the concrete friction observed while building ChromeBridge through DevSpace's shell-write-restricted path.

## Why this is one release

The observed issues share one boundary: StackMarshal Core already decides the right state mutation, but the host transport still asks too much of the reasoning model and leaves a few operational edges around transaction admission, growing payloads, relocation, recovery, and Windows shell discovery.

v1.2.1 therefore improves that transport as one coherent unit instead of weakening the signed-plan model or splitting each symptom into a separate patch release.

## Pending plans are now a Core admission invariant

An unacknowledged HostWrite plan blocks every project-mutating StackMarshal command regardless of whether the next caller selects `--write-mode host` or direct mode. This catches transport-mode mistakes before any project command runs.

The pending record is also created with an exclusive filesystem create. A second process cannot win a check/write race and replace the single pending slot. A malformed or partial pending record remains fail-closed rather than being overwritten.

`host-write status`, `check`, `ack`, `recover`, and explicit `abort` remain the allowed control-plane operations while a transaction is pending.

## `events.jsonl` no longer travels as a full-file mutation

The largest avoidable HostWrite payload was append-only evidence. v1.2.0 represented an event append as a full previous file plus a full next file. The semantic mutation stayed small while the transport grew with total run history.

v1.2.1 adds `append_text`. A growing evidence append now carries:

- the expected whole-file SHA-256 and byte size,
- at most 512 characters of signed `expected_tail`,
- only the new `append_content` and its SHA-256,
- the required whole-file postimage SHA-256.

For DevSpace, the normal compact path is an exact native edit using `expected_tail` as `oldText` and `expected_tail + append_content` as `newText`. Core still hashes the complete file at ACK, so reducing transport size does not reduce completion authority.

The full signed preimage is stored outside the repository as a content-addressed recovery blob rather than inlined into every plan.

## Recovery no longer requires reconstructing the old file by hand

`stackmarshal host-write recover --plan-id <id>` returns preimages derived from the verified pending plan or its content-addressed recovery blob. It never writes project state itself. The operator/host restores that content only through the native host file API, then reruns the original transaction.

This preserves the shell-write restriction while making failed preimage/postimage recovery explicit and reproducible.

## Workspace relocation is a signed operation

Intentional workspace moves no longer have to masquerade as repository bootstrap.

Before moving:

```text
stackmarshal relocate prepare --to <new-root> --run-id <id>
```

After moving:

```text
stackmarshal relocate accept --permit-id <id> --run-id <run-id>
```

Use `--write-mode host` on `relocate accept` when the destination host prohibits shell-side project writes.

Acceptance requires the pre-move signed deliverable fingerprint, portable repository identity, Git HEAD and dirty state to match after the move. The event reason is `workspace_relocation`. A later `git init` remains a separate `workspace_repository_bootstrap` identity migration.

## Windows Git Bash gets a managed shim

Windows installs continue to use the managed `stackmarshal.cmd` launcher for PowerShell/cmd resolution. v1.2.1 also installs an extensionless `stackmarshal` shell shim in the same managed `bin` directory so Git Bash can resolve bare `stackmarshal` without knowing the install path.

Doctor treats these co-located files as one launcher family, so the compatibility shim does not create a false `multiple_stackmarshal_launchers_on_path` warning.

## Host adapter contract

The host adapter contract is documented in [HOST_WRITE_ADAPTER.md](HOST_WRITE_ADAPTER.md). Core owns mutation contents, preimage requirements, postimage requirements, plan identity and final ACK. A host adapter may batch native writes if the host supports it, but it may not claim multi-file atomicity when the host only exposes per-file operations.

Current DevSpace file tools are per-file. v1.2.1 reduces the protocol and payload overhead that StackMarshal controls, but does not pretend that StackMarshal can add a transactional DevSpace API from inside its own CLI.

## Compatibility

Normal Codex/CLI direct-write behavior is unchanged. Existing v1.2.0 `write_text` HostWrite plans remain readable/acknowledgeable after the update; new plans use schema 1.1 and may include `append_text` operations.

`migrate` remains outside project HostWrite planning. Managed `pin` and `repair` remain installation operations rather than project mutations.

## Release quality gate

The final release commit must pass the normal candidate/immutable/published gates, public multi-platform CI and CodeQL, plus real Windows dogfood for:

- managed v1.2.0 -> v1.2.1 update,
- PowerShell/cmd launcher continuity,
- bare Git Bash `stackmarshal --version`,
- no false multiple-launcher doctor warning from the managed shell shim,
- real DevSpace `append_text` apply/ACK,
- pending-plan block after a plan has already been applied but not acknowledged,
- signed relocation preserving the same run across a physical workspace move.

## Roadmap

The previously planned operator UX / fully non-invasive state-placement work moves to v1.2.2. Claude Code moves to v1.2.3, Gemini CLI to v1.2.4, and adapter-conformance polish to v1.2.5.
