# Architecture

StackMarshal has two layers. The Codex Skill contains the orchestration procedure,
progressive-disclosure references, and a dependency-free fallback. The Python Core
owns deterministic state, budgets, candidate scoring, failure fingerprints, progress,
fail-closed security classification, lock verification, user-local HMAC authentication for live
run/task authority, checkpoints, and acquisition receipts, repository-lineage identity, and CLI
output.

Core does not execute arbitrary candidate instructions. The host Agent performs
reasoning and implementation through an `AgentAdapter`; v1 provides a Codex environment
adapter. Discovery, acquisition, and workspace mutation are protocol boundaries so future
Agent adapters can reuse state and policy without changing the deterministic state machine.

v1.2.3 separates the workflow profile from the run mode. `quick-explore` permits a
short safe-experiment path without a full preliminary architecture/task graph, but
still requires acceptance evidence and verification before `COMPLETE`. `build` keeps
the previous workflow; `release-audit` additionally requires actual hashed test,
security and artifact files. Only discovery/replan counters are soft in quick-explore,
and exceeding them must carry an explicit reason. Resource and security bounds remain hard.

Git ownership is inspected before new work. Bootstrap initializes only the requested
workspace without an automatic commit; nested workspaces need explicit approval.
`task amend` retains the superseded evidence as authenticated history but clears
completion for changed criteria. `evidence reconcile` is read-only and never promotes
work performed outside the recorded run into completion authority.

Workspace mutation has two transports. `DirectFilesystemWriter` preserves the existing CLI-owned
atomic write path for normal Codex/CLI operation. `HostPlanWorkspaceWriter` is used only when a host
prohibits shell-side project mutation but provides a native file API. In that mode Core simulates the
same mutation semantics in memory, emits an HMAC-authenticated write plan outside the project, and
requires the host to apply canonical contained targets through its own write/edit API.

HostWrite schema 1.1 has two mutation shapes. `write_text` keeps the exact UTF-8 preimage plus its
SHA-256. `append_text`, used for growing evidence such as `events.jsonl`, carries the whole-file
preimage SHA-256/size, at most 512 characters of signed tail, only the appended bytes, and the final
whole-file SHA-256. The previous full append preimage is retained as a content-addressed user-local
recovery blob instead of being copied into each plan. A separate `host-write ack` always verifies the
actual final postimages before clearing the pending plan.

The single pending-plan slot is a Core admission invariant, not a host-mode convention. Project
mutations in either direct or host mode are rejected while a plan is pending, and the pending record
is created with exclusive filesystem semantics so concurrent producers cannot replace it. Host
adapters may batch operations when their native API supports that capability, but StackMarshal does
not claim multi-file atomicity for per-file APIs such as the current DevSpace write/edit interface.
See [HOST_WRITE_ADAPTER.md](HOST_WRITE_ADAPTER.md).

Project decisions live in `.stackmarshal/project/`; ephemeral runs live in
`.stackmarshal/runs/<run-id>/`. The shared integrity signing key, pending host-write plans/receipts,
content-addressed HostWrite recovery blobs, and workspace-relocation permits live in the user's
external StackMarshal state directory, never in the repository. Canonical `run.json` and `task-graph.json`
are authenticated before they are accepted as execution/completion authority. Events are
append-only JSONL. Architecture is frozen before task execution. Mandatory work discovered after the
task graph is admitted only from `REPLAN`, consuming both architecture-replan and scope-addition
budget; normal task addition remains phase-bound. Verification-only fixes use a separate bounded
`VERIFICATION -> CORRECTION -> VERIFICATION` lane so they do not consume architecture replan budget.

`stackmarshal next` is a read-only view over this authority. It exposes the current state, blockers,
legal transitions, incomplete mandatory tasks, and completion prerequisites without creating a
recovery plan. Host-observed tool telemetry is similarly narrow: a named source may submit a
monotonic absolute counter, and Core charges only the positive delta.

A formal checkpoint records a signed resume phase. Explicitly resumable terminal states can return
the same run id to `RUNNING` only after checkpoint HMAC, project identity, Git/dirty state, and exact
Git or non-Git worktree fingerprint validation. Intentional workspace relocation uses a separate
signed pre-move permit containing the deliverable fingerprint, portable repository identity, HEAD and
dirty state. `relocate accept` migrates the run (and any signed checkpoint) only if those facts remain
unchanged, recording `workspace_relocation`; a later `git init` remains the distinct
`workspace_repository_bootstrap` migration. Legacy unsigned run/task records are never converted into
trusted live authority; migration archives their original bytes with SHA-256 evidence and starts fresh
signed authority instead.

Build-mode terminal success uses a two-step integrity boundary. `stackmarshal finalize` runs while
VERIFICATION is still active, regenerates StackMarshal-owned project bookkeeping, and seals the
verified terminal deliverable fingerprint plus the complete `.stackmarshal/project/` evidence tree.
Git-only housekeeping may then update repository HEAD without changing those sealed contents.
`COMPLETE` validates the finalization seal and records the terminal HEAD, dirty paths/status, and
workspace fingerprint; it does not write project content after the terminal boundary.
