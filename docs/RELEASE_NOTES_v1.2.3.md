# StackMarshal v1.2.3

Exploration can change direction without weakening completion evidence.

## Git from the start

`git inspect` distinguishes an existing repository, an unborn repository, a workspace inside an ancestor repository, and a workspace without Git. `git bootstrap` creates only the missing repository. It never stages or commits user files; nested repositories require an explicit flag. Shell-write-restricted hosts cannot bypass their mutation policy through Git.

## Workflow profiles

- `quick-explore` permits `ENVIRONMENT_AUDIT -> IMPLEMENTATION` for safe local experiments. A task with acceptance evidence and normal verification is still needed for `COMPLETE`.
- `build` retains the existing research, architecture and task flow.
- `release-audit` additionally checks hash-bound test, security and artifact evidence at completion.

The `research_rounds` and `architecture_replans` thresholds are soft only in `quick-explore`, and only with an explicit recorded reason. Tool-call, scope, repeated-failure and safety limits remain hard.

## Evidence and changing plans

`task amend` allows a REPLAN-phase revision of acceptance criteria. Superseded evidence stays in the signed task history, while the amended task returns to pending.

`evidence reconcile` compares a signed run and checkpoint with current Git and worktree facts without writing files or treating outside work as verified completion.

Windows Git subprocess decoding uses UTF-8 and terminal porcelain captures unquoted Unicode paths.
Checkpoint summaries distinguish an uninitialized workspace from a repository with no first commit.

## Verification

The new tests cover safe repository initialization, nested-repository refusal, quick-explore transitions, soft-limit reasons, immutable hard budgets, task-evidence invalidation, stale checkpoint detection and release-evidence hashes. Existing quality and release gates still apply.
