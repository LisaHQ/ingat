# ADR-0012 Step model and execution semantics

**English** · [Tiếng Việt](0012-step-model-and-execution-semantics.vi.md)

**Status:** Accepted.

**In plain words:** One executor runs every operation as a list of typed steps from a fixed set. Each step is written down before it runs; helper containers get predictable names and are always stopped before the lock is released; and an interrupted backup or check is undone automatically, so it never blocks the next one.

## Context

The predecessor's kind × phase tables, supersession and pairing produced deadlocks and dead ends (found by its reviews and real-Docker runs). Killing a `compose exec/run` client does not stop the server-side process (Lens B must-fix). A crashed nightly backup must not block the next one (Lens B must-fix).

## Decision

One generic executor over a closed set of typed steps with classes scratch / reversible / forward, atomic or interruptible ([LIFECYCLE.md](../LIFECYCLE.md) §3.3); intent fsynced before effect; one open operation per instance, with tasks a pause allows journaled inside the paused operation; deterministic, labelled task containers named per attempt (`<instance>-x<seq>-<step>-a<attempt>`), stopped and awaited before the lock is released; an orphan check before `resume`, `abandon` or a new mutation that refuses on a running op-labelled container and turns an exited one into recorded evidence before removing it; undeclared non-zero exits of write tasks are `unknown`; mutating `exec` only inside isolated projects; every task of `backup.steps` and `backup.verify` is scratch whatever its effect (and must be idempotent unless read); auto-abandon only for operation kinds without a forward step (prepare, backup, verify, drill), undoing reversible steps, recorded and visible in `status`.

## Alternatives

Per-kind state machines (rejected: the predecessor's defects). No auto-abandon (rejected: blocks scheduled backups). Auto-abandon of any non-destructive operation (rejected: Lens A saw it as hiding failures; scoping it to operation kinds that cannot pass a forward point, with a recorded undo and teardown, keeps the record). Classifying a backup task by its own effect (rejected: the SQLite consumer's backup records its outcome in the app, which would make a crashed nightly backup a forward step that blocks every later backup and freezes the live app on abandon).

## Consequences

The crash matrix is generated from step lists. `resolve` (class D) arrives in M3; in M1-M2 every forward step of both consumers is idempotent or observable, so it is not needed.
