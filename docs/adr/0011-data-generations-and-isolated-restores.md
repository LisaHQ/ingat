# ADR-0011 Data generations; restores and drills in isolated projects

**Status:** Accepted.

## Context

Both consumers already restore into a new location (their own runbooks' restore procedures). Starting store services on a new generation inside the live project would recreate the live database under a running backend (Lens A must-fix). The predecessor's same-UUID-only restore made disaster recovery impossible.

## Decision

Stores bind to generations `g<N>` (external volumes or directories). A restore fills `g<N+1>` in the isolated project `<instance>--r<seq>` (real instance secrets, holds, internal networks, no ports), tears it down, stops the live project, switches the pointer and starts the live project. Drills use `<instance>--t<seq>` with throwaway secrets and `t<seq>` generations, torn down by a closed deletion.

## Alternatives

In-place restore (rejected: safety floor F7, never overwrite data; [LIFECYCLE.md](../LIFECYCLE.md) §1). Restore staging inside the live project (rejected: Lens A must-fix).

## Consequences

Old generations cost disk until `prune --generations` (M3). A CI test asserts that no live writer mounts an unswitched generation.
