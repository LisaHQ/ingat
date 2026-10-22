# ADR-0005 Operations that change Docker run in a detached executor container

**Status:** Accepted.

**In plain words:** Almost every change to Docker runs in a separate helper container that keeps going on its own; your terminal only follows along. A dropped SSH connection or a closed window therefore cannot stop a backup, an update or a data migration half-way. The exception is a task that talks to you in the terminal: it runs from your own window.

## Context

The predecessor's runner handled only SIGTERM; SIGHUP killed the controller while a mutating child kept running after the lock was released (blocking findings of its last review). Whether `docker run -i -t` through SSH proxies signals and survives a session drop is unverified (Lens A and Lens B both flagged it). Lens B preferred a detached executor only as a fallback; Lens A asked for it by default.

## Decision

Every lock-taking operation that changes Docker runs in `ingat-exec-<instance>` (`docker run -d --rm --stop-timeout 120`), or `ingat-exec--host` for host scope, started by the CLI after planning and approval; the CLI only follows. The container name is a second mutex. Cancel is a file honoured at step boundaries and in wait loops; SIGINT, SIGTERM, SIGHUP and SIGQUIT to the executor are cancel requests. In the CLI run only foreground one-step tasks with terminal I/O and three short commands that change tool state but no Docker object: `host init`, `init`, `secret set` ([ARCHITECTURE.md](../ARCHITECTURE.md) §4).

## Alternatives

Attached tool container that ignores SIGHUP (rejected as the default: correctness then depends on unverified docker-client behaviour on DSM, on the reliability tier of the priority order). Host daemon (rejected: a listener and lifecycle states).

## Consequences

About 250 extra lines (follower, cancel, attach, vanished-executor detection). Session loss can never stop a migration half-way. `docker kill` of the executor is the documented last resort, covered by the orphan check ([ADR-0012](0012-step-model-and-execution-semantics.md)).
