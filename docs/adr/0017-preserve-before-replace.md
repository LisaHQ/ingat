# ADR-0017 Preserve before replace on every writer or data image change

**Status:** Accepted, pending owner decision OD-4.

**In plain words:** Any update that changes the program of a part that writes data first stops those parts, takes a backup copy and checks it; only then does the data update run. This costs some minutes of downtime per release, and the owner decides whether that is acceptable (OD-4).

## Context

The PostgreSQL consumer's release script takes the in-freeze backup only when a migration is pending; the SQLite consumer's runbook takes its paired backup online before stopping, so writes between the two are missing from the pair. Deciding "migration pending" at plan time needs a candidate probe, which creates containers and breaks plan purity.

## Decision

Any deploy that changes a writer or data-service image (or any image of a `migrates_on_start` app) stops writers, captures and verifies a pre-change bundle, then migrates or starts. Migrate runs every time; both consumers' migrate commands are idempotent.

## Alternatives

Evidence-based freeze (a candidate schema probe step, skip the bundle when nothing is pending): less downtime for code-only releases, more branches and a probe before approval.

## Consequences

Every release of the PostgreSQL consumer stops its backend for the dump plus verify time (and then the migrate and activation): the web shell loads, but no data can be read or written. The time is unmeasured until M2 slice 6 measures it on the target host. The owner decides whether that cost is acceptable (owner decision OD-4).
