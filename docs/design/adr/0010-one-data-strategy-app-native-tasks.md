# ADR-0010 One data strategy in v1: app-native tasks

**English** · [Tiếng Việt](0010-one-data-strategy-app-native-tasks.vi.md)

**Status:** Superseded by [ADR-0031](0031-data-providers.md) (2026-10-19): a second strategy, `provider`, joins `tasks`; the reasoning against engine code in `src/` stands.

**In plain words:** The first data rule: apps back up and restore with their own commands, and Ingat does everything around them (stopping, sealing, checking, keeping). ADR-0031 replaced it by adding a second way; its reason for keeping database code out of Ingat's core still holds.

## Context

Real Docker found engine defects inside the predecessor's PostgreSQL code (its real-Docker runs showed them). Generic engine code cannot carry app semantics such as the SQLite consumer's outbound-mail hold or the PostgreSQL consumer's role grants and invariant check after a restore.

## Decision

Strategies `tasks` and `none` only. Ingat owns quiescence, staging, the payload rule, hashing, sealing, verification, retention and the drill; the app's tasks produce and consume its own backup format.

## Alternatives

Built-in engine strategies (rejected). A generic `cold` copy (deferred: trigger in [ROADMAP.md](../ROADMAP.md) §4, which includes an app to adopt whose backup command the owner cannot run against its foreign deployment; data generations already remove the need for an emergency copy).

## Consequences

No engine literals in the core (lint). The PostgreSQL consumer's own pre-release backup check in its migrate command keeps verifying its own backup format inside Ingat's bundle (the payload is exactly that format), a second, independent layer of defence. Replacing that check by an Ingat attestation was considered and rejected: it would remove an independent verification to save one layer of app code, and the consumer needs no change to keep it.
