## Summary

## Requirement / acceptance links

## Security and trust impact

- [ ] No new secret, billing, publication, privileged, global-write, or external-binary path
- [ ] New approval boundaries are documented and tested
- [ ] External content remains untrusted data

## Bounded-convergence impact

- [ ] No stop limit was removed or weakened
- [ ] New retries, replans, research re-entry, or scope growth are explicitly bounded

## Verification

- [ ] Ruff
- [ ] mypy strict
- [ ] pytest and coverage >= 85%
- [ ] package build and Twine check
- [ ] documentation updated

## Migration / rollback
