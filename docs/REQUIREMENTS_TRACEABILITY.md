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
| State | Deterministic live transitions, one authoritative RUNNING run, nested-repository bootstrap lineage, phase snapshots, append-only events, pre-COMPLETE finalization and terminal repository seal | `state.py`, `cli.py` | unit/integration and `tests/test_live_orchestration_contract.py` |
| Task graph | Canonical machine-readable task state, generated Markdown view, mandatory evidence gate before COMPLETE, finalization hash seal | `taskgraph.py`, `cli.py`, `schemas/task-graph.schema.json` | CLI/integration and live-orchestration contract tests |
| Stop harness | Priority, live activity budgets, per-task attempts, failure fingerprints, stagnation, repository config may tighten but not expand safety budgets | `harness.py`, `budget.py`, `activity.py`, `failure.py`, `progress.py`, `config.py` | stop/activity/Nextpatch/config-hardening tests |
| Checkpoint | HMAC integrity, repository-lineage identity, exact worktree fingerprint, strict HEAD/dirty validation, do-not-repeat | `checkpoint.py`, `integrity.py`, `state.py` | unit/adversarial tests |
| CLI | Specified commands and machine JSON | `cli.py` | CLI integration tests |
| Security | Untrusted text, fail-closed command classes including Git helper/alias/global-option escapes, redaction, strict run IDs, workspace-state symlink/junction containment, release/installer boundaries | `security.py`, `cli.py`, `config.py`, release builder, verified installer, Skill policy | adversarial tests/Codex Security |
| Installation | One-command install/update/repair, prerequisite approval, version pinning, checksum verification, isolated venv, atomic rollback, Skill backup, PATH consent, versioned restart-pending marker, stale-host fallback refusal, host/Skill/CLI readiness doctor | `scripts/install.ps1`, `scripts/install.sh`, `scripts/installer.py`, `skills/stackmarshal/scripts/stackmarshal_core.py`, `cli.py` | `tests/test_installer.py`, `tests/test_distribution.py`, `tests/test_nextpatch.py`, cross-platform installer smoke, `docs/INSTALLATION_AUDIT.md` |
| Distribution | Skill folder, Python package, CI, bootstrap/installer assets, release assets, pyproject-authoritative version coherence, staged release gate | `skills/`, `pyproject.toml`, workflows, `scripts/version_contract.py`, `scripts/release_gate.py`, release builder | distribution tests, build/release gates, release-manifest coherence evidence |
| Documentation | English primary, Japanese secondary | `README.md`, `README.ja.md` | link/readability checks |

`COMPLETE` is permitted only when every mandatory row has passing evidence and the
release checklist contains no unresolved blocker.
