# RFC Process

Use an RFC for changes that alter StackMarshal's public state schema, stop semantics,
approval boundaries, adapter protocol, Skill invocation behavior, or release format.
Small bug fixes and documentation corrections do not require an RFC.

## Process

1. Open a GitHub Discussion in the **RFC** category with the problem, constraints, and alternatives.
2. Link a draft document under `docs/rfcs/NNNN-short-title.md` when implementation details matter.
3. Keep the review period open for at least seven days unless an active security issue requires faster action.
4. Record the decision, rejected alternatives, migration impact, and verification plan.
5. Merge implementation only after the RFC is marked **Accepted**.

## Required sections

- Summary
- Motivation
- Security and trust impact
- Bounded-convergence impact
- State/schema compatibility
- Alternatives
- Migration and rollback
- Test plan

An accepted RFC does not override StackMarshal's priority order: safety, bounded convergence,
reproducibility, explicit user intent, context efficiency, and completion rate.
