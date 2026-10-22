# ADR-0015 Probes: three kinds, stability windows, any-of values, store readiness

**English** · [Tiếng Việt](0015-probes-and-store-readiness.vi.md)

**Status:** Accepted.

**In plain words:** Ingat checks that an app is ready in three ways (Docker's health status, a command inside the container, an HTTP request), and a check can be required to stay good for a set time. Each time a database starts, Ingat waits until the readiness check the app declares for it passes, not just until its container is running; Docker's health status alone was rejected as the only kind of check.

## Context

A PostgreSQL container reported healthy while the image's temporary init server was running (a predecessor tool's real-Docker run showed it); a Compose `pg_isready` healthcheck uses the socket, and `run --no-deps` skips `depends_on` conditions. The PostgreSQL consumer's code-only rollback path reports its schema as `accepted`. HTTP probes from helper containers break the no-trace rule (Lens A must-fix).

## Decision

Probe kinds `health`, `exec` (inside the target container) and `http` (from the Ingat container over host loopback to the published port; not applicable in isolation). `stable` windows; JSON expectations accept a value or an any-of list (a schema `accepted` beside `current` for `rollback --accept-schema`, M3); headers match exactly (`header_equals`) or by substring (`header_contains`); every data-store start waits for its store's `ready` probe (for a PostgreSQL store, as in `fx-pg`: `pg_isready -h 127.0.0.1`, 15 s stable). Declarative `[[smoke]]` reproduces the PostgreSQL consumer's shell smoke test at the same strength (for example an exact `cache-control: no-cache` header; schema `current` only, `accepted` only on the rollback path); the image identity check is built in.

## Alternatives

Helper probe containers (rejected: trace). Joining instance networks (rejected: a mutation). Docker health only (rejected: the init-server case above).

## Consequences

Smoke parity exists in M2, before the PostgreSQL consumer's shell smoke test can be retired (Lens B must-fix).
