# ADR-0008 Filesystem layout: plain POSIX root, root-written backups root

**English** · [Tiếng Việt](0008-filesystem-layout.vi.md)

**Status:** Accepted; revised 2026-10-14, before any implementation, for platform-neutral host support ([ADR-0025](0025-host-baseline.md)): the backups root is generic, and the DSM shared folder is its form in the DSM profile. The earlier title was "Filesystem layout: plain POSIX root, root-written backup share".

**In plain words:** Ingat's own folder is a plain folder that only root can open. A backup is first written there, then copied into a separate backups folder that only root can write to; that folder is the one your off-site copy is taken from.

## Context

Hosts differ in how the backups root can be protected and copied off the host. On DSM, shared folders carry ACLs that override POSIX modes; task containers run as fixed uids (10001 in both consumers' images) and can be denied. On Btrfs volumes a rename from one subvolume to another fails with `EXDEV`, and on any host the two roots may sit on different filesystems (on an ext4 volume within one filesystem a rename would work, but one publishing path serves every layout). Hyper Backup protects shared folders, not the Docker root (`@docker` on the volume where Container Manager is installed); on a Linux host, restic, borg or rsync copy a directory. SQLite WAL needs local storage.

## Decision

`INGAT_ROOT` is a plain `root:root 0700` directory on a local filesystem (on DSM created over SSH, never a shared folder) and holds all state, stages, input copies and bind generations. `INGAT_BACKUPS` is written only by root and no other account can write into it, so retention never works in a tree other users can change: on a Linux host a `root:root 0700` directory, on DSM a shared folder that administrators can only read (no DSM account can write into it over SMB). Publishing is copy into `.incoming-<id>/`, fsync, rename within the backups root. Retention deletes with no-follow, descriptor-relative walks and re-proves each item. Containers never mount anything from the backups root. Certification checks the owner, mode and write access of both roots, and on DSM the ACL markers and the share permission ([ARCHITECTURE.md](../ARCHITECTURE.md) §7.2, §10.4).

## Alternatives

Stage in the backups root (rejected: Lens A must-fix). Put state in a shared folder (rejected: ACLs, SMB exposure). Mount the Docker root for space checks (rejected: Lens B must-fix; the probe volume measures it).

## Consequences

A bundle is written twice (stage, then the backups root); capacity checks count both. Whether `/volume1/ingat` survives a DSM update is risk R4 ([ARCHITECTURE.md](../ARCHITECTURE.md) §12), checked at the first DSM update.
