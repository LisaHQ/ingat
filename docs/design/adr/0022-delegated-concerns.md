# ADR-0022 Delegated concerns

**English** · [Tiếng Việt](0022-delegated-concerns.vi.md)

**Status:** Accepted; revised 2026-10-14, before any implementation, for platform-neutral host support ([ADR-0025](0025-host-baseline.md)): the delegated tools are the platform's own, and `schedule render` is M3 only. The Context and Alternatives sections were added the same day. Superseded in part (2026-10-19) by [ADR-0032](0032-local-session-bound-web-view.md) (the no-listener consequence, narrowed to one named exception) and by [ADR-0033](0033-commercial-boundary-report-and-hosted-service.md) (the notification sentence of the Decision); the rest stands.

**In plain words:** HTTPS and routing, off-site copies with encryption, scheduling and failure emails stay with the machine's own tools (a reverse proxy, restic, borg, rsync or Hyper Backup, systemd, cron or Task Scheduler). Ingat gives them stable exit codes and helpers. ADR-0032 (one local web view) and ADR-0033 (one outbound status report) later narrowed two parts.

## Context

Every host Ingat targets already provides a reverse proxy, backup tools and a scheduler: Caddy or nginx, restic, borg or rsync, and systemd timers or cron on a Linux host; the DSM reverse proxy, Hyper Backup and Task Scheduler on DSM. restic, borg and Hyper Backup encrypt client-side, and rsync can copy to an encrypted destination. Ingat is a short-lived command-line tool with no daemon or listener ([ARCHITECTURE.md](../ARCHITECTURE.md) §1.4).

## Decision

TLS and routing (the host's reverse proxy: Caddy, nginx or the DSM reverse proxy), off-host copies and encryption (the platform's tools to an owner-managed destination off the host: restic, borg or rsync on a Linux host; Hyper Backup on DSM to another NAS or an off-site target), scheduling and notification (systemd timers with `OnFailure=`, cron with `MAILTO`, DSM Task Scheduler; exit codes) stay outside Ingat. Recovery never relies on snapshots (on DSM, Snapshot Replication exists only on Btrfs volumes): bundles plus the off-host copy are the whole recovery path. Ingat provides stable exit codes, `status --json`, `schedule render` for systemd, cron and DSM Task Scheduler (M3) and a documented backup layout plus `import` (M4).

## Alternatives

Built-in encryption, off-host replication, a scheduler daemon or a notifier in Ingat (rejected: the non-goals in [ARCHITECTURE.md](../ARCHITECTURE.md) §1.4; each would duplicate a mature platform tool and add key management, a daemon or a listener to a tool that has none).

## Consequences

No daemon, no notifier, no network listener in Ingat.
