# Workflow

Use the deterministic state order defined by StackMarshal Core:

`INVOCATION_CHECK -> INTENT_NORMALIZATION -> ENVIRONMENT_AUDIT -> RESEARCH_GATE -> LANDSCAPE_RESEARCH? -> CAPABILITY_MAPPING -> CAPABILITY_DISCOVERY -> TRUST_EVALUATION -> ISOLATED_POC? -> ARCHITECTURE_FREEZE -> TASK_GRAPH -> IMPLEMENTATION? -> VERIFICATION? -> COMPLETE|CHECKPOINTING`.

Research mode exits after architecture freeze. Prepare mode exits after task graph.
Build mode continues through implementation and verification. Resume starts from a
validated checkpoint. Every transition is appended to `events.jsonl`; history is
never rewritten. Architecture changes after freeze require a decision record.

One authoritative run owns a bounded job. `start` rejects a second RUNNING run in the
same workspace. A nested workspace does not inherit an ancestor repository as its
identity; if the workspace initializes its own repository or creates its first commit,
the same run records an explicit project-identity migration event.

Transitions are live boundaries, not a retrospective checklist. The Core records a
workspace fingerprint on entry to each phase. Build mode records implementation and
verification activity while those phases are current, consumes observable budget
through `activity record`, and keeps the canonical JSON task graph synchronized.
`COMPLETE` fails closed when mandatory task evidence is stale or live-build evidence
is inconsistent.
