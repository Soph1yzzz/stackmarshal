# Requirements Traceability Matrix

| Area | Requirement | Implementation | Evidence |
|---|---|---|---|
| Invocation | Explicit semantic invocation only; EN/JA/ZH and `$stackmarshal` | `state.validate_invocation`, Skill invocation gate | `tests/test_core.py`, fallback CLI tests |
| Modes | research, prepare, build, resume | `Mode`, `infer_mode` | unit tests |
| Environment | OS, Python, Git, dirty state, native Skills | `adapters/codex.py` | audit CLI and integration tests |
| Research | Gate, staged bounded research, evidence compression | `research.py`, Skill policy | unit tests and docs |
| Capability | Status map and cross-ecosystem categories | schemas and Skill policy | schema tests |
| Candidate trust | 100-point scoring and hard disqualifiers | `scoring.py` | unit tests |
| Acquisition | Pinning, manifest inspection, HMAC-signed receipt, replacement-aware exact-file rollback | `acquisition.py`, `integrity.py`, `security.py`, `lock.py` | adversarial/unit tests |
| Freeze | Decision record and capped research re-entry | Skill workflow and templates | forward test matrix |
| State | Deterministic transitions and append-only events | `state.py` | unit/integration tests |
| Stop harness | Priority, budgets, failure fingerprints, stagnation | `harness.py`, `budget.py`, `failure.py`, `progress.py` | stop tests |
| Checkpoint | HMAC integrity, repository-lineage identity, exact worktree fingerprint, strict HEAD/dirty validation, do-not-repeat | `checkpoint.py`, `integrity.py`, `state.py` | unit/adversarial tests |
| CLI | Specified commands and machine JSON | `cli.py` | CLI integration tests |
| Security | Untrusted text, fail-closed command classes, redaction, strict run IDs, workspace/release/installer boundaries | `security.py`, `cli.py`, release builder, verified installer, Skill policy | adversarial tests/Codex Security |
| Installation | One-command install/update/repair, prerequisite approval, version pinning, checksum verification, isolated venv, atomic rollback, Skill backup, PATH consent | `scripts/install.ps1`, `scripts/install.sh`, `scripts/installer.py` | `tests/test_installer.py`, cross-platform installer smoke, `docs/INSTALLATION_AUDIT.md` |
| Distribution | Skill folder, Python package, CI, bootstrap/installer assets, release assets | `skills/`, `pyproject.toml`, workflows, release scripts | build/release checks |
| Documentation | English primary, Japanese secondary | `README.md`, `README.ja.md` | link/readability checks |

`COMPLETE` is permitted only when every mandatory row has passing evidence and the
release checklist contains no unresolved blocker.
