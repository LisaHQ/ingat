# Ingat

> **ingat**: deploy and update Docker Compose apps on one host from immutable sources. It keeps your data before every risky change, counts a backup as restorable only after an isolated restore of that exact sealed backup, resumes safely after an interruption, and deletes only what it can prove it owns.

*Ingat* is Malay/Indonesian for "remember, be aware, be careful". In Tagalog *ingat* means care and caution, and the everyday farewell *Ingat!* means "take care!". Say it close to "in-ngat".

**Where it runs.** Any machine or appliance with a local Linux Docker Engine (24.0 or later) and Compose v2: a bare-metal server, a VM or VPS, a NAS that offers Docker (Synology or any other vendor), a small board, on `x86_64`, or on `arm64` for the Engine lines its CI lane passes. Mutating commands need an Engine line that CI tests (today 24.0 and one exact 29.x; on arm64 29.x only). Platform differences are detected capabilities and a certification per platform build, never a branch on a platform name, vendor or model ([Hosts](#hosts), below).

## Status

| What | State |
|---|---|
| Phase | **Design only.** This repository holds the design package; no code exists. |
| Implemented | Nothing. Nothing of Ingat has run on Docker or on a host. |
| Decided | The architecture, the safety floors, the approval classes, the manifest format (a draft until the M2 exit gate freezes it), the milestones and the ADRs in [`docs/adr/`](docs/adr/README.md). Owner decisions OD-1 (the name Ingat), OD-2 (the LisaHQ namespace) and OD-3 (a public repository and image with generic content only), all on 2026-10-14. |
| Open | Owner decisions OD-4 to OD-11, recorded in the owner's private notes. The docs tag every dependency on one as **Open OD-n**. |
| Host facts | The first real deployment is a Synology NAS on DSM 7.4.1 with Container Manager 24.0.2; a read-only probe of it supplied the facts of the first platform profile on 2026-10-14 ([`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §11.2). Generic Linux hosts are covered by the CI lanes from M1. The runtime behaviours the design depends on are M0 spike items ([`docs/ROADMAP.md`](docs/ROADMAP.md)); none is verified yet. |
| License | [Apache License 2.0](LICENSE). |

Ingat is rebuilt from scratch and replaces an earlier in-house deployment controller. It has **no compatibility** with it: no shared labels, roots, records, bundles, volumes or images, and it reads none of its formats. Taking over a deployment made outside Ingat is a product feature (adoption, below).

## Features

The full feature set is committed scope through M4.

| Feature | Milestone |
|---|---|
| Host install, version gate and host certification on any Linux Docker host (generic Linux covered by the CI lanes; the first platform profile, Synology DSM 7.4 with Container Manager 24.0.2, certified on the first host) | M1 (the first committed generic Linux certification M4) |
| Deploy from an exact git commit or an image digest; first install with pauses | M1 (image digests M2) |
| Update with schema and data migration, only after a sealed, verified pre-change bundle taken with writers stopped | M1 (bind stores), M2 (volume stores and data services), M3 (data-service image changes) |
| Backup: sealed, hashed bundles, scheduled and manual, with retention | M1 |
| Verify (hash plus the app's verify tasks) and an isolated restore-test drill | M1 |
| Restore into a new data generation, never over current data | M2 |
| Rollback: an older release by deploy plus the paired restore (M1-M2); the `rollback` command, code-only or with data (M3) | M1-M3 |
| Purge, gated by a restore-tested final bundle | M3 |
| Monitoring with stable exit codes; `schedule render` for systemd timers, cron and DSM Task Scheduler | M3 |
| Disaster recovery: import, cross-host restore, restore into a new instance | M4 |
| Adoption of a Compose deployment Ingat did not create, by importing a payload of the app's own backup command and restoring it into a new instance; Ingat never touches the foreign project | M4 |
| Generic Linux host certification (VPS or server): runbook and the first committed certification | M4 slice 12, when such a host is available |
| Tool self-upgrade, self-rollback and state migration commands | M5, on a trigger |

**Generality rule.** A new app needs a manifest (`ingat.toml`) in its own repository, never a core change, and a new host platform needs a certification, never a platform branch ([`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §11.3).

### Milestones

| Milestone | Goal | Estimate |
|---|---|---|
| M0 Decisions and host facts | Host facts certified by `facts.sh`, runtime spike on the first host and in CI, image build location decided (OD-11) | 1 week |
| M1 Walking skeleton: first real consumer | `lite-test` (the SQLite consumer) on the first host, the first real deployment on a Synology NAS (a support-tier-2 platform), end to end through the detached executor; the CI support-tier-1 lanes cover generic Linux | 3.5 weeks |
| M2 PostgreSQL consumer staging and restores | `pg-staging` on the first host (the Synology NAS); restores into a new generation for both consumers; plan hand-over to agents; manifest schema frozen | 2.5 weeks |
| M3 PostgreSQL consumer production readiness | Rollback, purge, prune, monitoring, scheduling renderers (systemd, cron, DSM), conformance, docs; `pg-prod` created (subject to owner decision OD-5) | 2.5 weeks |
| M4 Disaster recovery, adoption and generic Linux certification | Import, cross-host restore, restore into a new instance, lineage, adoption by payload import; the generic Linux host certification (VPS or server) once such a host is available | 2.5 weeks |
| M5 Tool evolution | Self-upgrade, state migration framework, generated reference | 1.5 weeks |

MVP (M0-M2): about 5.5k runtime lines in 7 slices. Completion (M0-M5): about 8.2k lines, 14 slices, about 13.5 weeks. Durations are estimates, not commitments ([`docs/ROADMAP.md`](docs/ROADMAP.md)).

## The design in ten lines

1. One pinned multi-arch container image (`linux/amd64` and `linux/arm64`; Python 3.13, the docker CLI, Compose v5, git, and buildx only if images are built on the host: owner decision OD-11) run by a 20-line root-only POSIX wrapper. A Linux server, a VPS and a NAS appliance run the same bytes; host Python and host Compose never matter. arm64 is claimed only for the Engine lines its CI lane passes (29.x only).
2. Every operation that changes Docker runs in a **detached executor container** (`ingat-exec-<instance>`), so a dropped SSH session or a scheduled run can never stop a migration half-way. The CLI only plans, asks for approval and follows; it runs only terminal tasks and three short state-only commands itself.
3. Compose always runs on **the app's own Compose files plus a generated override** that pins every service to a recorded image ID, adds stable ownership labels (never a per-deployment value, so unchanged services are never recreated), sets an explicit logging driver and binds data generations. The resolved `config` output is used only for the policy check and the fingerprint.
4. Each app keeps its data semantics in its own image. The **app manifest** `ingat.toml` lives in the app repository, is read from the exact commit being deployed, and declares typed tasks (backup, restore, verify, migrate, checks) with exact exit-code maps.
5. **Preserve before replace**: any change of a writer or data-service image stops writers, takes a sealed and verified pre-change bundle, then migrates. Restores never overwrite: they fill a **new data generation** in an isolated `<instance>--r<seq>` project, then switch a pointer. Adoption imports a payload of the app's own backup command and restores it into a new instance the same way; Ingat never touches a foreign object.
6. Data stores are ready only after a **stable TCP readiness probe**, never because a container reports healthy (a predecessor tool's real-Docker run showed a database container reporting healthy while its image's temporary init server was still running).
7. A **closed step log** (intent before effect, observe before retry), deterministic per-attempt task-container names, and one open operation per instance make every interruption resumable or abandonable, with no dead ends; backups have no forward step, so a crashed nightly backup never blocks the next one.
8. **Approval classes**: read-only and non-destructive work runs unattended; changes need a typed name or an owner-given plan hash; destructive work needs a typed challenge on a real terminal and is never accepted by plan hash. This guards against agent mistakes; operations agents' own tool deny rules enforce it (owner decision OD-10).
9. **Real Docker is the gate** on every push (upstream dind 24.0.2, the Engine and API floor, and one exact 29.x, plus an arm64 lane), with a generated crash matrix, an upgrade suite and a "refusal leaves no trace" test. Support claims name only tested combinations, and every host also needs a certification of its platform build; a vendor-built engine such as Synology's Container Manager needs a committed certification per build line.
10. **First real consumer** (`lite-test`, an instance of the SQLite consumer, on the first host) at the end of M1, about 4.5 weeks after the repository starts; `pg-staging` (the PostgreSQL consumer) at the end of M2, about 7 weeks; rollback, purge, disaster recovery and adoption follow in M3-M4 as committed scope.

## Hosts

Ingat runs on one host with a local Linux Docker Engine and Compose v2, on any distribution or appliance. Summary of [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §11.1:

| Support tier | Hosts | Ingat support |
|---|---|---|
| **Support tier 1** | Linux hosts (bare metal, VM, VPS or a board) running upstream Docker Engine (docker-ce or a distribution package) on an Engine line that CI tests (today 24.0 and one exact 29.x), on `x86_64`, or on `arm64` for the lines its arm64 lane passes (29.x only) | The CI lanes cover it from M1; mutating commands (gate tier 2) need a local `ingat selftest --host` certification of the host's platform build, again after every kernel, OS or Engine update (scheduled drills refuse until then). The first committed generic Linux certification (VPS or server) is Planned for M4 slice 12. |
| **Support tier 2** | Vendor-built engines on appliances: Synology DSM 7.4 or later with Container Manager 24.0.2 or later (Synology's build of Engine 24.0.2, API 1.43) first, other vendors later | Each platform build line needs a committed certification from the full checklist, and every update a local `ingat selftest --host`, while nightly online backups continue and scheduled drills refuse until then. DSM is the first real deployment: no certification exists yet, and the first is an M1 exit-gate item. DSM 7.4 reaches end of maintenance about June 2028, so a move to the next DSM line is a planned re-certification. |
| **Not supported in v1** | Rootless Docker; Docker Desktop on Windows or macOS for production (development only); Podman; Kubernetes or Swarm; multi-host; Docker Engine older than 24.0 (API below 1.43), which also excludes Synology DSM 7.1 and earlier with the legacy Docker package (Engine 20.10, API 1.41, Compose v1) | No CI lane or certification will be added. |

Platforms differ, and Ingat handles each difference as a detected capability, never by platform name: it refuses a non-zero `cpus` limit at plan time on a host without CPU CFS quota, logs through the `local` driver whatever the daemon default (terminal tasks and the CLI through `none`), records an old runc (CVE-2024-21626) or missing seccomp as a host risk, depends on no particular storage driver or cgroup version, and rests recovery on sealed bundles plus an off-host encrypted copy made with the platform's tools, never on snapshots. The first platform profile, DSM 7.4.1 with Container Manager 24.0.2-1706, shows most of these traits at once (a vendor kernel, 4.4.x on many DSM 7.x platforms; runc 1.1.7; aufs or btrfs storage by volume filesystem; logging driver `db`; cgroup v1; AppArmor without seccomp; no CPU CFS quota; live restore off). Upstream dind cannot reproduce a vendor Engine, so only host certification covers it. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §11.2.

### Minimum host requirements

Summary of [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §11.4:

- **Software:** a local Linux Docker Engine 24.0 or later (API 1.43 or later) with Compose v2 or later (the `docker compose` plugin), reachable through the local socket as root; on Linux, docker-ce from Docker's repository pinned by version, or a distribution package on a tested Engine line.
- **Access and scheduling:** SSH (or a console) with an account that can `sudo` to root; a scheduler that runs root jobs and mails failures: systemd timers, cron, or the platform's scheduler such as DSM Task Scheduler.
- **CPU:** `x86_64` (amd64) or `arm64`, arm64 only for the Engine lines its CI lane passes (29.x only). Ingat's own image targets each architecture's baseline; an app image must exist for the host's architecture and may require a higher level (for example RHEL or UBI 9 based images need x86-64-v2), which the per-image canary checks.
- **RAM:** Ingat itself needs little (not measured yet; M0 records it); the apps dictate the rest. A drill starts a second copy of an app's data services, so plan for the live instances plus one drill copy. Recommended, unmeasured: at least 4 GB for one PostgreSQL-backed app, 8 GB or more for several stateful apps with weekly drills.
- **Disk:** room for the retained bundles, one extra data generation during a restore, and the images.
- **Synology:** DSM 7.4 or later with Container Manager 24.0.2 or later (its `docker compose` plugin present).

Meeting these does not make a host supported: every platform build still needs its host certification, and support claims name only tested combinations.

## Documentation

| File | What it holds |
|---|---|
| [`README.md`](README.md) | This file: status, features, design summary, hosts, conventions and names |
| [`CLAUDE.md`](CLAUDE.md) | Instructions for AI development agents and contributors |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Product scope, runtime and distribution, execution model, modules, on-disk layout, security model, testing strategy, hosts, support matrix and minimum host requirements |
| [`docs/LIFECYCLE.md`](docs/LIFECYCLE.md) | Safety floors, approval classes, the operation and instance state machines, every operation step by step (adoption included), data strategies, exit codes, scheduled jobs |
| [`docs/MANIFEST_SPEC.md`](docs/MANIFEST_SPEC.md) | The app manifest (`ingat.toml`) and instance config (`instance.toml`) schemas, with complete generic examples |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Milestones M0-M5 with exit gates, sizes and triggers |
| [`docs/adr/README.md`](docs/adr/README.md) | Index of the numbered architecture decision records (`docs/adr/NNNN-*.md`) |

Install and command documentation arrive with M1; until then [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §3.4 and [`docs/LIFECYCLE.md`](docs/LIFECYCLE.md) §2 describe the designed install and command set. Docs stay English; operator runbooks get Vietnamese mirrors under `docs/runbooks/vi/` (Planned M3).

## Conventions used in every document

- **Status tags**: **Decided** (part of the design), **Planned Mx** (decided, built in milestone x), **Open OD-n** (needs an owner decision), **Unverified** (a platform fact the M0 spike or a later spike must confirm).
- **One verdict vocabulary** for gates, CI and reports: `PASS`, `FAIL`, `BLOCKED`.
- **Owner decisions** are cited as "owner decision OD-n". OD-1, OD-2 and OD-3 are decided; the others are open and recorded in the owner's private notes, which are not part of this repository.
- **Generic consumers.** The design is driven by two real apps, named here only by generic aliases:
  - *the PostgreSQL consumer*: a multi-service web app (PostgreSQL, a backend and a web service) with an explicit migrate step, role grants after a restore and an invariant-check command; mirrored by the fixture `fx-pg`;
  - *the SQLite consumer*: a single-container app with SQLite in a bind-mounted data directory, an online app-native backup, an outbound mail queue and a migrate at start; mirrored by the fixture `fx-lite`;
  - `fx-web`: a stateless fixture.

  Example instance names: `pg-staging`, `pg-prod`, `lite-test`, `site`.
- **The predecessor** is "an earlier in-house deployment controller". Lessons from it appear as short generic reasons, never as citations.

## Names

| Item | Value |
|---|---|
| Product | Ingat |
| CLI | `ingat` |
| Repository | `github.com/LisaHQ/ingat` |
| Environment prefix | `INGAT_` (for example `INGAT_ROOT`, `INGAT_BACKUPS`) |
| Label namespace | `io.github.lisahq.ingat.` (for example `io.github.lisahq.ingat.instance`) |
| Image | `ghcr.io/lisahq/ingat` (public, multi-arch `linux/amd64` and `linux/arm64`, pulled by digest) |
| Default roots | `/srv/ingat` (tool state: a plain POSIX directory, `root:root 0700`) and `/srv/ingat-backups` (sealed bundles, written only by root); wrapper `/srv/ingat/bin/ingat`; both configurable at install (`--root`, `--backups`) |
| DSM profile roots | `/volume1/ingat` (never a shared folder) and `/volume1/ingat-backups` (a DSM shared folder, read-only for administrators, written only by root, the Hyper Backup source); wrapper `/volume1/ingat/bin/ingat`; passed at install, not a code default |
| Derived Docker names | Compose project `<instance>`, executor `ingat-exec-<instance>`, isolated projects `<instance>--r<seq>` (restore) and `<instance>--t<seq>` (drill), volumes `<instance>_<store>_g<N>` |

In code these names live only in `src/ingat/brand.py` and the wrapper template (ADR-0003); docs use them literally.

## Contributing and AI agents

Read [`CLAUDE.md`](CLAUDE.md) before changing anything. It is the canonical instruction file for AI development agents and applies to human contributors too: the public content rule (generic content only, no consumer or host values), layering, safety floors, testing and the commit-description format. Development agents never run Ingat, `docker` or `install.sh` against a real host; they use CI and scratch dind daemons only.

## License

Ingat is licensed under the [Apache License 2.0](LICENSE).
