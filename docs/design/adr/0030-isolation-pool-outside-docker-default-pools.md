# ADR-0030 The isolation subnet pool lies outside Docker's default address pools

**Status:** Accepted (2026-10-16).

**In plain words:** Test restores (and, from M2, restore staging) take their private networks from `10.250.0.0/20`, a range Docker does not use by default, so Docker's own networks no longer fill it up; if none of its 16 slots is free, Ingat stops with a clear message instead.

## Context

`host init` records an isolation pool from which an executor allocates one free `/24` for each isolated project (drills; restore staging from M2). The design default was `172.30.192.0/20` ([LIFECYCLE.md](../LIFECYCLE.md) §4.1, [ARCHITECTURE.md](../ARCHITECTURE.md) §7.4). Docker's built-in default address pools, used when `DefaultAddressPools` is not configured, hand out `172.17.0.0/16` through `172.31.0.0/16` and `192.168.0.0/16` in `/20` chunks. Once the daemon gives a network `172.30.0.0/16`, no `/24` of the pool is free and every drill refuses. The local integration runs on scratch daemons (upstream Engine 24.0.2 and 29.9.0) used up Docker's default pools, which shows that a busy host can reach that range.

## Decision

The default isolation pool becomes `10.250.0.0/20` (sixteen `/24`s), outside every Docker default pool. The allocation rule is unchanged: the first `/24` that no allocation entry and no network on the daemon uses. A host whose own networks use that range still gets a free `/24` or a clear refusal.

## Alternatives

Keep `172.30.192.0/20` (rejected: it collides with Docker's own defaults on any host with enough networks). Derive the pool from the daemon's `DefaultAddressPools` at `host init` (rejected: the field is absent when defaults apply, and a derived pool can still be taken later). A host-configurable pool (rejected for now: a new install option with no consumer need yet).

## Consequences

`host.json` written before this change keeps its recorded pool; `host init` on a new host records the new default. Isolated networks are internal and carry no routes, so the range needs no routing on the host.
