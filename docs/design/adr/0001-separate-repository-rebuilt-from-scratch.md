# ADR-0001 A separate repository, rebuilt from scratch

**English** · [Tiếng Việt](0001-separate-repository-rebuilt-from-scratch.vi.md)

**Status:** Accepted (owner directive, 2026-10-14).

**In plain words:** Ingat is a new, separate project written from scratch. It shares nothing with the older in-house tool it replaces and cannot read that tool's data; the apps on the host today are reinstalled fresh, without moving their old data.

## Context

The predecessor, an earlier in-house deployment controller, lived inside the repository of the PostgreSQL consumer (about 29k runtime lines, most of them in one script). It never ran on the target host, its last review gate required changes, and its Compose allowlist rejected the SQLite consumer and could not express the PostgreSQL consumer's production Compose file. The PostgreSQL consumer is not in production.

## Decision

A new public repository `github.com/LisaHQ/ingat` (owner decisions OD-2 and OD-3), with its own version line. No compatibility with the predecessor: no shared labels, roots, records, bundle formats, volumes or images; no reading or migration of its instances. Its code is reused only as ideas (the reuse analysis stays in the owner's notes). Today's data is not migrated either: the owner deletes today's containers on the target host and reinstalls both consumers from scratch (owner, 2026-10-14). Generic adoption of a foreign Compose deployment ([ADR-0024](0024-adoption-by-payload-import.md)) is a separate product feature that reads no predecessor format.

## Alternatives

Extract and refactor the predecessor (rejected: about 85-90% of its lines serve actors and layouts the new tool does not have; an audit judged extraction a rewrite). Keep it inside the PostgreSQL consumer's repository (rejected: there is a second consumer, the SQLite consumer, and there are generic sites).

## Consequences

The predecessor and its docs can be deleted from the consumer's repository (tracked in the owner's notes). Every persistent identifier is new and must be fixed before the first real resource exists ([ADR-0003](0003-name-namespaces-and-brand-module.md)).
