# StackMarshal v1.2.0

StackMarshal v1.2.0 adds a second project-mutation transport for hosts that prohibit shell-side project writes while preserving the existing direct filesystem path for ordinary Codex/CLI use.

## Why this release is a minor version

The v1.1.x line hardened recovery, version management, and installer cleanup without changing the Core's extension shape. Dogfooding StackMarshal inside a DevSpace-managed OSS workflow exposed a different class of limitation: StackMarshal could enforce its phase, acceptance, retry, checkpoint, and verification contracts, but DevSpace's shell contract forbids project-file mutation from shell commands. Because the StackMarshal CLI itself owns `.stackmarshal/` evidence writes, the formal run could not be completed even though the host could safely modify files through its native write/edit API.

v1.2.0 therefore adds a new public transport boundary rather than weakening either product's rules.

## Direct mode remains unchanged

Normal Codex/CLI operation still uses the existing direct filesystem writer. `stackmarshal init`, `start`, task/activity updates, checkpoints, finalization, and other project mutations keep their prior direct/atomic behavior unless the caller explicitly selects host mode.

No existing workflow is required to adopt host-write mode.

## HostWriteAdapter foundation

Project-mutating commands may use:

```text
--write-mode host
```

In host mode Core computes the same mutation semantics but does not write project files directly. Instead it emits an HMAC-authenticated host-write plan stored outside the project. Each operation binds:

- a canonical relative project path,
- the exact expected preimage and its SHA-256, or an explicit expectation that the path is absent,
- the required UTF-8 postimage content and SHA-256,
- the project root and repository-lineage identity,
- the originating StackMarshal command and result.

The host transport then uses its native file API and completes the handshake with:

```text
stackmarshal host-write status
stackmarshal host-write check --plan-id <id>
stackmarshal host-write ack --plan-id <id>
stackmarshal host-write abort --plan-id <id> --reason "..."
```

`check` rejects a changed preimage before application. `ack` re-reads the actual project files and rejects missing, unsafe, or wrong postimages. A pending plan blocks later project mutations so two authority updates cannot overlap. The host executes bytes; it does not gain StackMarshal phase, completion, or evidence authority.

## Security boundary

Host-write plans and receipts use the same user-local HMAC integrity boundary as live StackMarshal authority and remain outside the repository. Plans accept only canonical contained project-relative paths and reject traversal, drive-qualified/backslash aliases, duplicate targets, unsupported operations, symlink/junction escapes, malformed preimage contracts, inconsistent content hashes, and tampered signed records.

`migrate`, managed `pin`, and managed `repair` are deliberately not project host-write operations in v1.2.0.

The focused v1.2.0 security review treats the host as a fallible transport, not trusted authority. Dedicated adversarial tests cover plan tampering, path escape/non-canonical paths, preimage races, wrong postimages, pending-plan serialization, incorrect plan IDs, abort/check/ack failure paths, and an end-to-end host-mediated StackMarshal lifecycle through finalization. The maintainer chose the documented focused review + adversarial suite + public CI + CodeQL path instead of a separate full Codex Security repository scan for this release.

## Windows repair cleanup follow-up

The real cleanup of the old Python Scripts 1.0.0 launcher used the existing explicit:

```text
stackmarshal repair --remove-shadowed
```

path and succeeded. That dogfood exposed another Windows residue case: same-version repair can leave an installer-created `.vMAJOR.MINOR.PATCH.old-<uuid>` swap backup while the old process still holds its `python.exe` open.

v1.2.0 extends the bounded deferred-cleanup helper to this exact installer-owned backup grammar. Unknown hidden directories are not swept, rollback behavior is unchanged, and cleanup still runs from the current/new managed Python after the originating CLI exits.

## Quality evidence before publication

Before publication the release must pass:

- full automated test suite,
- Ruff,
- strict mypy,
- branch-aware coverage gate of at least 85%,
- package build and Twine validation,
- version-contract coherence,
- candidate and immutable release gates,
- public Windows/macOS/Linux CI and CodeQL on the exact release commit,
- published-asset re-download verification,
- real Windows managed pin from v1.1.6 to v1.2.0,
- verification that the stale unmanaged 1.0.0 launcher is gone and managed installer residue converges to the v1.2.0 installation.

## Roadmap

The previously planned operator UX / fully non-invasive state-placement work moves to v1.2.1. Claude Code adapter work moves to v1.2.2, Gemini CLI to v1.2.3, and adapter-conformance polish to v1.2.4. v1.2.0 is intentionally limited to the host-write transport foundation plus the directly observed Windows repair-cleanup follow-up.
