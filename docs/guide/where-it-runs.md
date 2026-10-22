# Where Ingat runs

**English** · [Tiếng Việt](where-it-runs.vi.md)

Which machines Ingat supports, and what a machine needs before you install it.

## What a machine needs

- A machine with **Linux, Docker Engine 24.0 or later and Docker Compose v2**: a server, a VM or VPS, a small board, or a NAS that runs Docker. Processor: `x86_64`, or `arm64` with Docker 29.9.
- **A tested Docker version, to make changes.** Ingat changes things only on a Docker version this release was tested with: today 24.0 or 29.9 on `x86_64`, 29.9 on `arm64`. On another version from 24.0 up it can only look and take backups that do not stop the app. Keep Docker from updating by itself ([operator guide §1](operator-guide.md#1-before-you-start)).
- **Root access**, usually over SSH (`sudo -i`).
- A **scheduler** for the nightly jobs (systemd timers, cron, or Task Scheduler on a Synology NAS) that emails you when a job fails.
- A tool that **copies your backups to another place** (restic, borg, rsync, or Hyper Backup on a Synology NAS).
- **Memory:** Ingat itself needs little. Plan for your apps, plus one extra copy of an app's data services while a test restore runs. Suggested, not yet measured: at least 4 GB for one app with PostgreSQL, 8 GB or more for several apps with weekly test restores.

Full list: [minimum host requirements](../design/ARCHITECTURE.md#114-minimum-host-requirements).

## Supported machines

Ingat handles the differences between machines by checking what each machine can do, never by its brand, vendor or model.

| | Machines | What they need |
|---|---|---|
| **Supported** | Linux on any distribution (server, VM, VPS or small board) with upstream Docker Engine on a line the CI tests: today 24.0 and 29.9 on `x86_64`, 29.9 on `arm64` | `ingat selftest --host` on the machine, again after every kernel, system or Docker update |
| **Supported, per certified build** | Appliances with their vendor's own Docker build. First: Synology DSM 7.4 or later with Container Manager 24.0.2 or later. Certified so far: DSM 7.4.1 build 90080 with Container Manager 24.0.2-1706 on `x86_64` | A committed certification for each build line, plus `ingat selftest --host` after every update |
| **Not supported** | Rootless Docker; Docker Desktop on Windows or macOS for real use (development only); Podman; Kubernetes or Swarm; several machines; Docker Engine older than 24.0, which rules out Synology DSM 7.1 and older with the old Docker package | No plans to add them in v1 |

Until a machine's system and Docker build is certified, Ingat still shows you everything and keeps making the backups that do not stop the app, but it refuses every change. More: [`docs/design/ARCHITECTURE.md`](../design/ARCHITECTURE.md#11-hosts-and-support-matrix) §11.

### Support tiers and platform traits, in the words of the spec

Summary of [`docs/design/ARCHITECTURE.md`](../design/ARCHITECTURE.md) §11.1-§11.2:

- **Support tier 1:** Linux hosts running upstream Docker Engine (docker-ce or a distribution package) on an Engine line CI tests, on `x86_64`, or on `arm64` for the lines its arm64 lane passes (29.x only). The CI lanes cover it from M1; mutating commands (gate tier 2) need a local `ingat selftest --host` certification of the host's platform build. The first committed generic Linux certification is Planned for M4 slice 12, once such a host is available.
- **Support tier 2:** vendor-built engines on appliances, Synology DSM 7.4 or later with Container Manager 24.0.2 or later (Synology's build of Engine 24.0.2, API 1.43) first. Each platform build line needs a committed certification from the full checklist, and every update a local `ingat selftest --host`, while nightly online backups continue and scheduled drills refuse until then. DSM 7.4 reaches end of maintenance about June 2028, so a move to the next DSM line is a planned re-certification.
- **Traits:** Ingat refuses a non-zero `cpus` limit at plan time on a host without CPU CFS quota, logs through the `local` driver whatever the daemon default (terminal tasks and the CLI through `none`), records an old runc (CVE-2024-21626) or missing seccomp as a host risk, depends on no particular storage driver or cgroup version, and rests recovery on sealed bundles plus an off-host encrypted copy made with the platform's tools, never on snapshots. Upstream dind cannot reproduce a vendor Engine, so only host certification covers one.

