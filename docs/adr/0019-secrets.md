# ADR-0019 Secrets

**Status:** Accepted.

## Context

The predecessor leaked a `.env` hash into stderr and the journal, and a password character into a parser error. Compose replaces a missing secret file with an empty directory.

## Decision

Secrets only as files ([ARCHITECTURE.md](../ARCHITECTURE.md) §9.4): generated once or set from stdin; regular non-empty file checked before every Compose call, a directory refused; redacting `Secret` type; errors name keys only; canary scan in CI; never in bundles; owner custody for disaster recovery (owner decision OD-9; `export-config` M4).

## Alternatives

Secrets as Compose interpolation variables (rejected: they would enter the model).

## Consequences

The SQLite consumer's mail password reaches the container only through the rendered 0600 env file until that app can read it from a file.
