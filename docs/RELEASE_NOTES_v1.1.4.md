# StackMarshal v1.1.4

StackMarshal v1.1.4 is a deliberately small version-management release. It takes the version-skew diagnostics introduced in v1.1.3 and adds the operator workflow needed to resolve and manage that state without retyping installer URLs.

## Added

### `stackmarshal pin`

After the one-time bootstrap, updates are now driven from the CLI:

```text
stackmarshal pin latest
stackmarshal pin 1.1.4
stackmarshal pin status
```

`pin latest` resolves the latest published stable GitHub Release. Exact pins require a semantic release version. Before executing the selected platform bootstrap, StackMarshal downloads the Release `SHA256SUMS`, verifies the bootstrap hash, and only then delegates to the existing atomic installer. The installer remains the single implementation for isolated venv replacement, Skill synchronization, rollback, PATH handling, downgrade protection, and restart markers.

### `stackmarshal version`

Human-oriented version inspection now reports the runtime CLI, managed pin, installed Skill, resolved launcher, and an `OK`, `UNPINNED`, or `DRIFTED` status. `stackmarshal --version` remains unchanged for scripts and prints only the runtime version.

## Changed

v1.1.3 intentionally treated every discovered StackMarshal launcher version on PATH as possible skew. Field use showed that this was too strict when the correct managed launcher resolves first and older launchers are merely shadowed later on PATH. v1.1.4 keeps those versions visible as warnings, but readiness is based on the authoritative runtime, managed install, installed Skill, and resolved launcher.

## Scope

This release intentionally contains only the pin/version workflow and the directly required diagnostic refinement. The previously planned non-invasive init, delivery audit, and compact CLI output work moves unchanged to v1.1.5.

## Security assurance

The change touches installer/update and PATH trust boundaries, so it receives focused source-backed review, adversarial pin/bootstrap checksum tests, the full test/coverage gates, public CI, and CodeQL. Under the risk-triggered release policy, a full repository Codex Security scan is not required unless the focused review identifies a material unresolved boundary change.
