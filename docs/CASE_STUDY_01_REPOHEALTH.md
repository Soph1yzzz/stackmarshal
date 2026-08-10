# Case Study #1 — RepoHealth

## Summary

This case study records a controlled Phase 3B dogfooding run in which Codex, explicitly invoked with StackMarshal, built a small OSS-readiness CLI from an almost-empty local directory.

The goal was not to maximize implementation difficulty. The goal was to test whether StackMarshal could structure a real Codex build around explicit requirements, capability mapping, architecture freeze, implementation, verification, and a terminal `COMPLETE` result without human technical intervention.

**Result: PASS, with integration follow-ups identified for the next StackMarshal patch.**

## Experiment design

The working directory initially contained only an empty `.gitignore`. It was intentionally not published or pushed to GitHub. The task required Codex to create an installable cross-platform CLI named **RepoHealth** that audits a local Git repository for basic OSS release readiness.

The requested checks included:

- README
- license
- Git/worktree state
- tracked, untracked, and dirty state
- tests
- CI configuration
- package/project metadata
- recognizable source layout
- actionable OSS-readiness gaps

The CLI had to provide both human-readable and JSON output, work offline at runtime, include tests and documentation, and pass appropriate lint/type/test/build quality gates.

Implementation details and dependency choices were deliberately left to Codex. Publication, release, deployment, GitHub push, global configuration changes, and workspace-external writes were forbidden.

## Invocation

The valid run used an explicit StackMarshal build invocation. The final accepted run recorded:

```text
$stackmarshal build RepoHealth Phase 3B accepted final
```

Mode: `build`  
Budget profile: `standard`

## Attempt #1 — excluded operator-error run

The first Phase 3B attempt produced a working RepoHealth implementation but was excluded as StackMarshal evidence because Codex had not been restarted after the Skill was installed.

The installer and README already required a restart. Because the host session was stale, the generated project imitated parts of the requested workflow but produced no StackMarshal run state. This was an operator setup error, not counted as a successful StackMarshal run.

The failure was useful because it established a concrete acceptance rule for the retry: StackMarshal execution evidence had to exist and be independently auditable.

## Attempt #2 — accepted run

After restarting Codex and confirming that the `stackmarshal` Skill was available, the experiment was repeated in a fresh empty directory.

### Evidence that StackMarshal was active before implementation

The initial StackMarshal run was created at approximately **22:15 JST**. Project-level StackMarshal artifacts were then written before application code:

| Approx. time (JST) | Evidence |
|---|---|
| 22:15:11 | StackMarshal run created |
| 22:16:00 | requirements, capability map, architecture decision, and task graph written |
| 22:16:50 | CLI implementation written |
| 22:17:38 | audit engine implementation written |
| 22:18:03 | tests written |
| 22:19:35 | implementation commit created |
| 22:21:19 | final documentation correction committed |

This ordering is important: the decision artifacts preceded the implementation rather than being authored only after the code existed.

## StackMarshal decisions

### Capability map

The run determined that all required capabilities were already available locally:

- CLI parsing: Python `argparse`
- filesystem inspection: `pathlib`
- JSON output: Python `json`
- Git inspection: fixed read-only Git subprocess commands
- packaging: setuptools/`pyproject.toml`
- testing: host pytest tooling

No third-party runtime dependency or external capability acquisition was necessary. Network services were explicitly prohibited.

This is a useful negative result: Research First did not force unnecessary web research or dependency acquisition when the capability map showed that the standard library and local Git were sufficient.

### Architecture freeze

The frozen design used a small Python 3.11+ package with two main responsibilities:

- `repohealth.audit`: filesystem classification and narrow Git adapter
- `repohealth.cli`: argument parsing, human rendering, JSON output, and exit behavior

Runtime dependencies: **zero**.

Rejected alternatives included Rich/Typer/Click, GitPython, and web API checks because they added unnecessary dependency or reproducibility cost for the requested scope.

## Generated artifact

RepoHealth was created as an installable Python CLI with:

- `src/` package layout
- README and MIT license
- `pyproject.toml`
- pytest tests
- Ruff configuration
- strict mypy configuration
- branch coverage gate
- GitHub Actions CI configuration
- wheel and source distribution build
- local wheel install smoke test

The CI matrix was configured for **Ubuntu, macOS, and Windows** with Python 3.11. Because this experiment intentionally did not push the repository to GitHub, the remote matrix itself was not executed; Windows behavior and all local gates were independently rerun after Codex finished.

## Verification

The accepted StackMarshal final report recorded:

- human CLI: 7/7 checks passed
- JSON CLI: schema version 1, 7/7 checks, 0 issues
- tests: **6 passed**
- Ruff: **PASS**
- mypy strict: **PASS**
- branch-aware coverage: **92%**, above the 85% gate
- package build: wheel + sdist produced
- local wheel install smoke: **PASS**
- Git worktree: clean

A separate post-run audit repeated the core quality gates and reproduced the same results on the Windows host.

## Independent adversarial checks

The post-run audit also replayed edge cases that had exposed defects in the invalid first attempt.

### Non-Git directory

A directory containing otherwise valid OSS files is now correctly reported with a failed Git check rather than being treated as fully ready.

### Detached HEAD

A valid repository in detached-HEAD state is still recognized as a Git worktree.

### Mixed tracked and untracked changes

A worktree containing both a tracked modification and an untracked file reports both categories in the structured Git details.

All three checks behaved as expected in Attempt #2.

## StackMarshal terminal evidence

The final accepted run reached:

```text
INVOCATION_CHECK
→ INTENT_NORMALIZATION
→ ENVIRONMENT_AUDIT
→ RESEARCH_GATE
→ CAPABILITY_MAPPING
→ CAPABILITY_DISCOVERY
→ TRUST_EVALUATION
→ ARCHITECTURE_FREEZE
→ TASK_GRAPH
→ IMPLEMENTATION
→ VERIFICATION
→ COMPLETE
```

Final status: `COMPLETE`.

The final run-state document also passed StackMarshal's own run-state validator.

## Findings discovered by dogfooding

The experiment passed, but it revealed integration issues that unit/forward testing had not made obvious:

1. **Repository-bootstrap identity:** the first run began before the child directory had its own `.git`, so identity initially resolved against the parent repository. After child `git init`, later runs used the new identity and the original run remained orphaned.
2. **Live state authority:** project artifacts were created before code, but the authoritative Core transition history was not consistently recorded at each real-time phase boundary. Later successful runs transitioned rapidly after most implementation work already existed.
3. **Budget accounting:** the successful run ended with `budget.used` counters still at zero despite real tool and implementation activity.
4. **Task-graph synchronization:** the project task graph still marked final quality verification as pending even though the final report contained passing evidence and the run was `COMPLETE`.

These findings did not invalidate the generated artifact or the fact that the Skill was active before implementation, but they identify the next integration-hardening work. They are intentionally tracked outside the public repository in the local `Nextpatch.md` working note until implemented.

## Generated-artifact follow-up

RepoHealth itself built successfully, but setuptools emitted a non-blocking deprecation warning for the license metadata format in `pyproject.toml`. That should be modernized before RepoHealth is ever published as its own package.

## Outcome

Phase 3B demonstrated that StackMarshal can guide Codex from a nearly empty workspace to a small, installable, tested CLI while keeping the requested implementation intentionally modest and the verification evidence explicit.

More importantly, the run produced useful negative evidence: real dogfooding exposed gaps in live state ownership, budget accounting, and project-record synchronization that were not blockers in the controlled unit/forward-test suite.

The result is therefore recorded as:

**Phase 3B: PASS**  
**Case Study #1: RepoHealth**  
**Next action: harden the discovered integration gaps in the next patch series rather than expanding v1 scope during this case study.**
