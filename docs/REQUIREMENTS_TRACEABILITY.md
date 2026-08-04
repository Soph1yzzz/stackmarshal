# Requirements Traceability Matrix

| Area | Requirement | Implementation | Evidence |
|---|---|---|---|
| Invocation | Explicit semantic invocation only; EN/JA/ZH and `$stackmarshal` | `state.validate_invocation`, Skill invocation gate | `tests/test_core.py`, fallback CLI tests |
| Modes | research, prepare, build, resume | `Mode`, `infer_mode` | unit tests |
| Environment | OS, Python, Git, dirty state, native Skills | `adapters/codex.py` | audit CLI and integration tests |
| Research | Gate, staged bounded research, evidence compression | `research.py`, Skill policy | unit tests and docs |
| Capability | Status map and cross-ecosystem categories | schemas and Skill policy | schema tests |
| Candidate trust | 100-point scoring and hard disqualifiers | `scoring.py` | unit tests |
| Acquisition | Pinning, manifest inspection, receipt, rollback | `acquisition.py`, `security.py`, `lock.py` | adversarial/unit tests |
| Freeze | Decision record and capped research re-entry | Skill workflow and templates | forward test matrix |
| State | Deterministic transitions and append-only events | `state.py` | unit/integration tests |
| Stop harness | Priority, budgets, failure fingerprints, stagnation | `harness.py`, `budget.py`, `failure.py`, `progress.py` | stop tests |
| Checkpoint | Integrity, identity, HEAD warning, do-not-repeat | `checkpoint.py` | unit tests |
| CLI | Specified commands and machine JSON | `cli.py` | CLI integration tests |
| Security | Untrusted text, command classes, redaction, workspace boundary | `security.py`, Skill policy | adversarial tests/security review |
| Distribution | Skill folder, Python package, CI, release assets | `skills/`, `pyproject.toml`, workflows, release script | build/release checks |
| Documentation | English primary, Japanese secondary | `README.md`, `README.ja.md` | link/readability checks |

`COMPLETE` is permitted only when every mandatory row has passing evidence and the
release checklist contains no unresolved blocker.
