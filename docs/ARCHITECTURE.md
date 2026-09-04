# Architecture

StackMarshal has two layers. The Codex Skill contains the orchestration procedure,
progressive-disclosure references, and a dependency-free fallback. The Python Core
owns deterministic state, budgets, candidate scoring, failure fingerprints, progress,
fail-closed security classification, lock verification, user-local HMAC authentication for live
run/task authority, checkpoints, and acquisition receipts, repository-lineage identity, and CLI
output.

Core does not execute arbitrary candidate instructions. The host Agent performs
reasoning and implementation through an `AgentAdapter`; v1 provides a Codex environment
adapter. Discovery and acquisition are protocol boundaries so future Agent adapters
can reuse state and policy without changing schemas.

Project decisions live in `.stackmarshal/project/`; ephemeral runs live in
`.stackmarshal/runs/<run-id>/`. The shared integrity signing key lives in the user's external
StackMarshal state directory, never in the repository. Canonical `run.json` and `task-graph.json`
are authenticated before they are accepted as execution/completion authority. Events are
append-only JSONL. Architecture is frozen before task execution, and a post-freeze architecture or
task-plan change requires a decision record. Verification-only fixes use a separate bounded
`VERIFICATION -> CORRECTION -> VERIFICATION` lane so they do not consume architecture replan budget.

A formal checkpoint records a signed resume phase. Explicitly resumable terminal states can return
the same run id to `RUNNING` only after checkpoint HMAC, project identity, Git/dirty state, and exact
Git or non-Git worktree fingerprint validation. Legacy unsigned run/task records are never converted
into trusted live authority; migration archives their original bytes with SHA-256 evidence and starts
fresh signed authority instead.

Build-mode terminal success uses a two-step integrity boundary. `stackmarshal finalize` runs while
VERIFICATION is still active, regenerates StackMarshal-owned project bookkeeping, and seals the
verified terminal deliverable fingerprint plus the complete `.stackmarshal/project/` evidence tree.
Git-only housekeeping may then update repository HEAD without changing those sealed contents.
`COMPLETE` validates the finalization seal and records the terminal HEAD, dirty paths/status, and
workspace fingerprint; it does not write project content after the terminal boundary.
