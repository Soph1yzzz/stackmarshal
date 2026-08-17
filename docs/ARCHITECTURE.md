# Architecture

StackMarshal has two layers. The Codex Skill contains the orchestration procedure,
progressive-disclosure references, and a dependency-free fallback. The Python Core
owns deterministic state, budgets, candidate scoring, failure fingerprints, progress,
fail-closed security classification, lock verification, HMAC-signed checkpoint integrity,
repository-lineage identity, and CLI output.

Core does not execute arbitrary candidate instructions. The host Agent performs
reasoning and implementation through an `AgentAdapter`; v1 provides a Codex environment
adapter. Discovery and acquisition are protocol boundaries so future Agent adapters
can reuse state and policy without changing schemas.

Project decisions live in `.stackmarshal/project/`; ephemeral runs live in
`.stackmarshal/runs/<run-id>/`. Checkpoint signing keys live in the user's external
StackMarshal state directory, never in the repository. Events are append-only JSONL. Architecture is frozen
before task execution, and a post-freeze change requires a decision record.

Build-mode terminal success uses a two-step integrity boundary. `stackmarshal finalize` runs while
VERIFICATION is still active, regenerates StackMarshal-owned project bookkeeping, and seals the
verified terminal deliverable fingerprint plus the complete `.stackmarshal/project/` evidence tree.
Git-only housekeeping may then update repository HEAD without changing those sealed contents.
`COMPLETE` validates the finalization seal and records the terminal HEAD, dirty paths/status, and
workspace fingerprint; it does not write project content after the terminal boundary.
