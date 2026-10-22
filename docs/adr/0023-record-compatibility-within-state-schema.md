# ADR-0023 Record compatibility within a state schema

**Status:** Accepted.

**In plain words:** Within one record version, Ingat's saved records only gain new optional fields whose defaults keep the old behaviour, so a newer Ingat and the previous one can both read them. Any other change needs a new record version and a migration command.

## Context

Real instances (`lite-test` from M1, `pg-staging` from M2) live through several tool upgrades done with `install.sh` before M5, while M2-M4 add record fields (`held_since`, `monitor.json`, inherited lineage, `imported` catalog entries, `adopted_from` and a bundle's `origin`). Hashed documents use strict JSON ([ARCHITECTURE.md](../ARCHITECTURE.md) §7.3). The predecessor had no upgrade path, and upgrade and reinstall must be a tested feature from the first release.

## Decision

Within one `state_schema`, changes are additive and optional only: a new field has a default that reproduces the old behaviour, and no field changes meaning or type. A reader keeps unknown fields of its own schema (a rewrite carries them over) and refuses a newer schema. Any other change bumps `state_schema` and ships a journaled `ingat state migrate` that copies the state first (M5). The upgrade suite runs from M1: release N-1 with an open operation refuses the upgrade; after it closes, N reads N-1 state, and `bin/ingat.prev` (N-1) reads the state N wrote ([ARCHITECTURE.md](../ARCHITECTURE.md) §3.5, §10.3).

## Alternatives

Defer every compatibility rule to M5's migration framework (rejected: real state exists from M1). Version every record type separately (rejected: one schema number per host is enough for one owner).

## Consequences

A field that cannot be additive forces a schema bump and `state migrate` earlier than M5; that is a re-plan trigger, not a silent change.
