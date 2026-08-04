# Workflow

Use the deterministic state order defined by StackMarshal Core:

`INVOCATION_CHECK -> INTENT_NORMALIZATION -> ENVIRONMENT_AUDIT -> RESEARCH_GATE -> LANDSCAPE_RESEARCH? -> CAPABILITY_MAPPING -> CAPABILITY_DISCOVERY -> TRUST_EVALUATION -> ISOLATED_POC? -> ARCHITECTURE_FREEZE -> TASK_GRAPH -> IMPLEMENTATION? -> VERIFICATION? -> COMPLETE|CHECKPOINTING`.

Research mode exits after architecture freeze. Prepare mode exits after task graph.
Build mode continues through implementation and verification. Resume starts from a
validated checkpoint. Every transition is appended to `events.jsonl`; history is
never rewritten. Architecture changes after freeze require a decision record.
