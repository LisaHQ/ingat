# ADR-0007 Image identity: pinned by ID, ledger, no image removal before M3

**Status:** Accepted.

## Context

Starting a re-tagged or rebuilt image silently breaks provenance and rollback (Lens B must-fix; a consumer need). The PostgreSQL consumer's release script refuses a release when the previous images are missing; the SQLite consumer's runbook never rebuilds an old tag.

## Decision

`prepare` records every image ID as a write-once ledger entry `host/images/<id>/<op>.json` with its tags, commit and provenance; references are computed from deployment records and the catalog, so no shared ledger file is ever rewritten. The override pins each service to its recorded ID with `pull_policy: never` and `build: !reset null`. A tag is reused only when its labels or the ledger prove provenance. Until M3 Ingat removes no image; from M3, `prune --images` (class D) removes only unreferenced ledger images. Fallback if spike S5 fails: verify tag → recorded ID immediately before every Compose call and refuse a mismatch.

## Alternatives

Trust tags (rejected). Registry digests only (rejected as the default while both consumers build on the host; adopted for both consumers if the owner chooses CI builds, the recommendation of owner decision OD-11).

## Consequences

Disk use grows until M3; `status` shows image disk use. Image IDs are host-local (classic and containerd stores differ), so cross-host identity uses commit plus labels (M4).
