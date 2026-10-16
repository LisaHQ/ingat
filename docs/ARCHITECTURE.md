# Ingat architecture

Status: **Decided** unless tagged otherwise. The M1 code exists and has run only on local scratch Docker daemons, not yet in CI or on a host ([README](../README.md#status)). Status tags: **Decided** (part of the design), **Planned Mx** (decided, built in milestone x), **Open OD-n** (needs an owner decision), **Unverified** (a platform fact the M0 spike or a later spike must confirm). Owner decisions are cited as OD-n: OD-1 (name), OD-2 (LisaHQ namespace), OD-3 (public repository) and OD-11 (app images built in each app's CI: ADR-0026) are decided; the others are open and recorded in the owner's notes. Operations and their state machines are in [`LIFECYCLE.md`](LIFECYCLE.md); manifest syntax is in [`MANIFEST_SPEC.md`](MANIFEST_SPEC.md); milestones are in [`ROADMAP.md`](ROADMAP.md); the reasons for each choice are in the ADRs ([`adr/README.md`](adr/README.md)).

## 1. Product

### 1.1 Statement

Ingat is a small command-line tool that installs, updates, backs up, verifies, restores and retires Docker Compose applications on **one** Docker host, and adopts a deployment it did not create from a payload of the app's own backup command (M4). Code, not configuration, enforces its guarantees (the safety floors F1-F17 in [`LIFECYCLE.md`](LIFECYCLE.md) §1):

- No data-changing step runs before a sealed, verified backup taken with writers stopped exists.
- A restore never overwrites data: it fills a new data generation, verifies it, then switches a pointer. The old generation is kept.
- A backup counts as restorable only after an isolated restore of that exact sealed bundle passed the app's checks.
- An interrupted operation can always be resumed or abandoned from its own step log; no state is a dead end.
- Nothing is deleted unless a closed plan lists it and each item is re-proved owned right before removal.

Ingat orchestrates. Each application keeps its data operations inside its own images and declares them in its app manifest (for example the command-line entry points that the PostgreSQL consumer and the SQLite consumer ship in their own images). The core contains no app or database-engine knowledge.

**Hosts.** A host is any machine with a local Linux Docker Engine (24.0 or later) and Compose v2, on any distribution or appliance: a bare-metal server, a VM or VPS, a NAS that offers Docker (Synology or any other vendor), a small board. Platform differences (CPU CFS quota, cgroup version, logging driver, storage driver, kernel, architecture, live restore, seccomp) are capabilities that Ingat detects, and each platform build is certified on its own; no code path branches on a platform name, vendor or model (§11). Support tiers and the platform profiles are in §11.1-§11.2.

### 1.2 Users

| Caller | How | Allowed (approval classes in [`LIFECYCLE.md`](LIFECYCLE.md) §2) |
|---|---|---|
| Owner | SSH, `sudo -i`, the wrapper `<INGAT_ROOT>/bin/ingat` (by default `/srv/ingat/bin/ingat`) | Everything; the only caller meant to answer a class D challenge |
| Operations agents in the owner's host session | Same binary | Class A and B freely; class C only with an owner-given plan hash; class D never. This is a checkpoint against mistakes that holds only for agents that obey it, **not** a security boundary against root: an agent that allocates a pty (for example `script -qc`) can type a challenge. Real enforcement is the agent's own tool deny rules (owner decision OD-10). Development agents working in the Ingat repository never touch a real host ([`CLAUDE.md`](../CLAUDE.md) §6). |
| Host scheduler (systemd timers, cron, or the platform's scheduler such as DSM Task Scheduler) | Absolute wrapper path, root, no terminal | `ingat scheduled …`: classes A and B only |
| App CI | `docker run <pinned ingat image> validate` (M1), `conformance` (M3) | Offline validation; real-Docker conformance in its own runner, never against a real host |

### 1.3 Consumers and scope

v1 consumers, described by shape only (this repository is public and generic: owner decision OD-3):

- **The PostgreSQL consumer**: a multi-service web app (PostgreSQL, backend and web) with an explicit migrate step, role grants after a restore and an invariant-check command; one staging instance now (`pg-staging`), a production instance later (`pg-prod`). Fixture `fx-pg` mirrors it (§10.2).
- **The SQLite consumer**: a single-container app with SQLite in a bind-mounted data directory, an online app-native backup, an outbound mail queue and migrate at start; one test instance now (`lite-test`), production later. Fixture `fx-lite` mirrors it.
- **Generic stateless sites** deployed by image digest (for example `site`). Fixture `fx-web` mirrors them.

Further in-house apps are planned; their stacks are unknown. Every capability names the consumer need it serves (ADR-0021), and a new app must fit without a core change (the generality rule, §11.3).

In scope (the full feature set the owner requires, 2026-10-14): host install and certification; instance init and secrets; build from an exact git commit or deploy an image digest; data-aware update (freeze, pre-change bundle, schema and data migration, ordered activation, smoke, refreeze); rollback; start/stop/restart; typed app tasks; backup, verify and isolated restore-test; restore into a new generation; retention; purge (M3); monitoring with stable exit codes (M3); disaster recovery: import, cross-host restore and restore into a new instance (M4); adoption of a running Compose deployment Ingat did not create (M4, [`LIFECYCLE.md`](LIFECYCLE.md) §4.16); any Linux Docker host (support tier 1, covered by the CI lanes from M1, with its first committed generic Linux certification in M4) and vendor appliances certified per platform build (support tier 2, Synology DSM first) (§11.1).

### 1.4 Non-goals (never)

- Multi-host orchestration, Swarm, Kubernetes, zero-downtime rollouts for stateful apps (both stateful consumers are single-writer).
- TLS termination or a reverse proxy (the host's reverse proxy, for example Caddy, nginx or the DSM reverse proxy, stays in front; services publish on `127.0.0.1` only).
- Encryption, off-host replication, a scheduler, a notification channel (the platform's tools own these: restic, borg or rsync on Linux, Hyper Backup on DSM, and the host scheduler with its failure mail).
- A web UI, daemon, agent, plugin system or host shell hooks.
- Auto-update or release discovery; refs are explicit and resolved once.
- Database-engine code in the core.
- Managing containers, volumes or networks Ingat did not create: a foreign object is never stopped, started, exec'd into, mounted, relabelled, restored into or deleted (adoption starts from a payload the owner produced: ADR-0024); ACL management (for example DSM ACLs).
- Compose passthrough for mutating verbs.
- Compatibility in any form with the earlier in-house deployment controller that Ingat replaces (ADR-0001).
- Protection against a concurrent root user or clicks in a vendor container GUI (for example Container Manager on DSM): these show up as drift (`changed-outside`, §11.2), they are not prevented.

## 2. System context

```
 owner / agent (SSH, sudo -i)        host scheduler: systemd, cron, DSM (root)
            │                                    │
            ▼                                    ▼
  /srv/ingat/bin/ingat  (root-owned POSIX wrapper, pins one image; default root)
            │  docker run --rm -i [-t] --init --network host  (same-path mounts)
            ▼
  ┌──────────────── CLI container (ephemeral) ────────────────┐
  │ parse → plan (pure) → approve → start executor → follow   │
  └───────────────┬───────────────────────────────────────────┘
                  │ docker run -d --rm --name ingat-exec-<instance>
                  ▼
  ┌──────────── executor container (one per operation) ──────┐
  │ flock instance lock → step log → typed steps             │
  │   docker compose -p <instance> -f <app files> -f override│
  └───────┬───────────────┬───────────────┬──────────────────┘
          ▼               ▼               ▼
   app project      side projects       tool state
   <instance>       <instance>--r<seq>  INGAT_ROOT /srv/ingat (plain POSIX dir, root 0700)
   (live)           <instance>--t<seq>  INGAT_BACKUPS /srv/ingat-backups (root-written)
                                        Docker volumes <instance>_<store>_g<N>
```

## 3. Runtime and distribution

### 3.1 Decision

Ingat ships as one multi-arch OCI image, `linux/amd64` and `linux/arm64` under one index digest, built from M1 (ADR-0004, ADR-0025), run through a root-owned POSIX `sh` wrapper. arm64 support is claimed only after its CI lane passes (§10.1); the first real deployment is amd64. Inside the image it is a normal Python 3.13 package, standard library first; a third-party dependency needs an ADR and must be hash-locked.

Why, against the host facts:

- Host Python differs by platform and is often old or absent: DSM's system `python3` is 3.8 (end of life) and Synology's Python 3.9 package is end of life. A host-run tool would inherit the oldest such floor; making root execution of host Python trustworthy is what grew the earlier in-house deployment controller's protected bootstrap to about 4.9k lines.
- The host's Engine and Compose differ by platform. A Linux host with Docker's packages runs upstream Engine 29.x; Container Manager 24.0.2-1706, the newest build for DSM 7.4, ships Synology's build of Engine 24.0.2 (API 1.43), and a later build may change the Engine, which the version gate and re-certification handle (ADR-0014). Synology never publishes the bundled Compose version; Container Manager 24.0.2-1706 ships the host Compose plugin v2.20.1 from mid-2023. Ingat never uses a host's Compose. The earlier in-house deployment controller silently fell back between Compose implementations.
- One image digest (a multi-arch index) pins the interpreter, docker CLI, Compose and git for every architecture, and CI tests exactly that artifact on each architecture it claims.
- Mounting the Docker socket is root-equivalent; every option needs root-equivalent Docker access anyway.

### 3.2 Image contents (pinned in `image/versions.lock`, checksums verified in the Dockerfile)

| Component | Pin | Note |
|---|---|---|
| Base | `python:3.13-slim-trixie@sha256:…` | Security support to 2029 |
| docker CLI | static build, exact version (29.9.0 today) | 29.x if it negotiates down to API 1.43 against Engine 24.0.2, else the newest 28.x that does (spike S4). `DOCKER_API_VERSION` is never set. |
| Compose plugin | exact v5.x (v5.6.0 today) | Fallback: the last v2.x that passes the Engine 24.0.2 lane. Never the host's Compose. |
| buildx | none | Not in the image: app images are built in each app's CI and pulled (owner decision OD-11, [ADR-0026](adr/0026-app-images-built-in-app-ci.md)). On-host builds return with buildx only through the deferred item in [`ROADMAP.md`](ROADMAP.md) §4. |
| git, openssh-client, tar | Debian packages | |
| `ingat` package and the `fx-lite` and `fx-web` fixtures | | Used by `selftest` and CI |

Every downloaded binary has one pinned checksum per architecture (`linux/amd64`, `linux/arm64`) in `versions.lock`; both variants are built from the same lock file into one multi-arch index. No secrets in the image. The image is public (`ghcr.io/lisahq/ingat`; owner decision OD-3), so hosts and app CI pull it anonymously by digest, and Docker selects the variant for the host's architecture.

### 3.3 Host wrapper

`install.sh` writes it; it is never edited by hand. Values are filled in at install.

```sh
#!/bin/sh
# /srv/ingat/bin/ingat — written by install.sh; replaced atomically by an upgrade; never edited by hand.
set -eu
INGAT_VERSION='0.1.0'
INGAT_IMAGE='ghcr.io/lisahq/ingat@sha256:<digest>'         # or sha256:<local image id> after an offline docker load
INGAT_ROOT='/srv/ingat'                                     # default roots; install --root/--backups set others
INGAT_BACKUPS='/srv/ingat-backups'
DOCKER='/usr/bin/docker'                                    # resolved once by install.sh (/usr/local/bin/docker on DSM)
PATH=/usr/bin:/bin; export PATH
[ "$(id -u)" -eq 0 ] || { echo "ingat: run as root (sudo -i)" >&2; exit 2; }
TTY=; if [ -t 0 ] && [ -t 1 ]; then TTY=-t; fi
FACTS=; for f in /etc.defaults/VERSION /etc/os-release; do [ -r "$f" ] && FACTS="$FACTS -v $f:/run/host$f:ro"; done
HOST_NAME=$(hostname); OPERATOR=${SUDO_USER:-root}
exec env -i PATH="$PATH" TERM="${TERM:-dumb}" "$DOCKER" run --rm -i $TTY --init --pull never --network host \
  --label io.github.lisahq.ingat.role=cli --log-driver none \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$INGAT_ROOT:$INGAT_ROOT" -v "$INGAT_BACKUPS:$INGAT_BACKUPS" \
  -v ingat-probe:/run/ingat/docker-root:ro $FACTS \
  -e TERM -e INGAT_ROOT="$INGAT_ROOT" -e INGAT_BACKUPS="$INGAT_BACKUPS" -e INGAT_IMAGE="$INGAT_IMAGE" \
  -e INGAT_WRAPPER_VERSION="$INGAT_VERSION" -e INGAT_HOST="$HOST_NAME" -e INGAT_OPERATOR="$OPERATOR" \
  "$INGAT_IMAGE" "$@"
```

Properties:

- **Same-path mounts.** Compose resolves bind, `env_file` and secret paths in the client while the daemon reads them on the host, so `INGAT_ROOT` and `INGAT_BACKUPS` are mounted at identical paths. Ingat refuses any Compose bind source outside the paths it provides (§9.5).
- **`env -i`** drops `DOCKER_HOST`, `DOCKER_CONTEXT`, `COMPOSE_*` and everything else from the operator's shell (Compose lets shell values override `--env-file`).
- **`--network host`** lets the tool reach services published on `127.0.0.1:<port>` for HTTP probes without joining any instance network (spike S7).
- **Release files.** The wrapper mounts each readable file of a fixed list of platform release files (today `/etc/os-release` and DSM's `/etc.defaults/VERSION`) read-only under `/run/host`; extending the list for a new appliance is a tool release, never a platform branch (§11.3).
- **Logging.** The daemon's default logging driver differs by platform (on DSM it is Synology's `db`: §11.2), so Ingat never relies on it. Terminal tasks and the CLI container log to the `none` driver, so a terminal secret is never written by any logging driver (F12): the CLI's output is the operator's terminal, `progress.log` and `steps.jsonl` are the record, and terminal tasks get `none` from the op-specific override (§6.2). The executor and services use `local` with rotation, so `ingat logs` and `SnapshotLogs` read a standard driver (whether `db` keeps logs of removed containers is Unverified).
- **Docker-root free space** is measured with `statvfs` on the tool-owned volume `ingat-probe` (created and labelled at install; it lives on the Docker root filesystem). The Docker root is never bind-mounted, so any Docker root layout (`/var/lib/docker` on a Linux host, `@docker` on a DSM volume) works unchanged.
- No listener, no long-running container. The CLI container exits when the command ends.
- A test-only crash hook (`INGAT_CRASH_AT`) exists only in test builds' environment; the wrapper's `env -i` can never pass it, and `doctor` flags it if seen.

### 3.4 Install

One `install.sh` serves every host. A platform profile (§11.2) adds only its own preparation and the values it passes; the install never branches on a platform name.

**Any host (owner, once):**

1. Prepare `INGAT_BACKUPS` and its off-host copy. On a Linux host it is a root-owned directory on a local filesystem (`root:root 0700`, by default `/srv/ingat-backups`), copied after the nightly backups to an owner-managed destination off the host by the platform's tool: restic or borg (both encrypt client-side) or rsync to an encrypted destination ([`LIFECYCLE.md`](LIFECYCLE.md) §5.9, §7). On DSM it is the shared folder of the profile below. Host certification checks that no account but root can write into it (§10.4).
2. As root (`sudo -i`), copy `install.sh` and `SHA256SUMS` from the GitHub release and run `sh install.sh --version 0.1.0` (default roots `--root /srv/ingat --backups /srv/ingat-backups`; a platform profile passes its own, and the DSM profile must). It:
   - checks that `--version` is a semantic version (it is written into the wrapper) and the release checksums, then pulls the image by digest, or `docker load`s the release tarball for the host's architecture (`--from-tar`) after checking its SHA-256;
   - creates `INGAT_ROOT` (and `INGAT_BACKUPS` when missing) as `root:root 0700`: a plain POSIX directory on a local filesystem;
   - creates the labelled volume `ingat-probe`;
   - runs `<image> selftest --offline` with the wrapper's own `docker run` flags (`--init --network host`), so an engine the wrapper cannot run on fails here, not at the first command;
   - resolves `command -v docker`, writes `bin/ingat.new`, fsyncs it and renames it to `bin/ingat` (keeping `bin/ingat.prev`); `--link /usr/local/bin/ingat` adds an optional convenience symlink.
3. `ingat host init` records the engine ID, DockerRootDir, versions, host capabilities (the typed `docker info` fields `CpuCfsQuota`, `CpuCfsPeriod` and `MemoryLimit`; spike S11) and allocation pools in `host.json`, plus the runc version, storage driver, image store, default logging driver, cgroup version, kernel, architecture, live restore and security options for the certification (§11), and creates the tool's empty Docker client directory `cache/docker-config/` (§6.1). Mutating commands refuse an untested or uncertified platform (§3.6).
4. Owner runs `facts.sh` (read-only host script shipped in the release) for the facts the tool container cannot see: the platform release and its Engine package build, filesystem type and layout of each root, and ACL markers where the platform has them (§10.4).
5. `ingat selftest --host` certifies the host's platform build for gate tier 2 (§3.6, §10.4).

Scheduled entries always call the wrapper by absolute path (`<INGAT_ROOT>/bin/ingat`); the symlink is a convenience only.

**Linux host with upstream Docker Engine (support tier 1, §11.1):** Docker Engine from Docker's repository (docker-ce) pinned by version string and held (`apt-mark hold` or the distribution's equivalent), or a distribution package whose Engine line is in `tested.json` (Debian 12 ships `docker.io` 20.10, below the 24.0 floor and unsupported; Debian 13 ships 26.1, which has no CI lane today, so gate tiers 0 and 1 only). Scheduled jobs run as systemd oneshot units and timers with `OnFailure=` (printed by `schedule render --systemd`, Planned M3), or as cron entries (`schedule render --cron`, Planned M3). The first committed generic Linux certification is Planned M4 slice 12.

**Platform profile: Synology DSM 7.4 with Container Manager 24.0.2 (support tier 2, §11.2):**

1. In DSM Control Panel create the shared folder `ingat-backups` with **read-only** access for administrators and no access for anyone else (root still writes; spike S9 confirms), and add it to a Hyper Backup task scheduled after the nightly backups, with client-side encryption, to an owner-managed destination off the NAS ([`LIFECYCLE.md`](LIFECYCLE.md) §5.9, §7). No DSM account can then write into it over SMB, and host certification checks the permission (§10.4).
2. Over SSH as root, run `sh install.sh --version 0.1.0 --root /volume1/ingat --backups /volume1/ingat-backups`. `/volume1/ingat` is created over SSH as a plain POSIX directory, **not** a shared folder, so it carries no Synology ACL and is not visible over SMB. Never accept the generic defaults on DSM: `/srv` would be on the DSM system partition, which is small and can be reset by a DSM update.
3. `facts.sh` also records the DSM-only facts: ACL markers, the Container Manager build, filesystem type and layout of the volume (ext4 or Btrfs).
4. Task Scheduler entries always call `/volume1/ingat/bin/ingat` by absolute path; an optional `/usr/local/bin/ingat` symlink is a convenience only, because DSM updates can reset the system partition.

### 3.5 Pinning and upgrade

- One tool version per host. Until M5 an upgrade is "run `install.sh` with the new version": pull by digest, `selftest --host` with the new image against the live daemon (it drives only its own `ingat-selftest-*` instances, so gate tier 2 never runs a tool version the host has not exercised; a `FAIL` keeps the old wrapper), atomic wrapper replace, keep `bin/ingat.prev`. It refuses while any operation is open. Running `bin/ingat.prev` is the way back.
- **Planned M5:** `ingat self-upgrade <version>` / `self-rollback`, the same steps as a command; prune never removes the current or previous tool image.
- **Record compatibility (ADR-0023).** Persisted state carries `state_schema = 1`. Within one `state_schema`, changes are additive and optional only: a new field has a default that reproduces the old behaviour, and no field changes meaning or type. A reader keeps unknown fields of its own schema (a rewrite of `record.json` carries them over unchanged) and refuses a newer schema. Any other change bumps `state_schema` and ships an explicit, journaled `ingat state migrate` that copies the state first (Planned M5). The records M2-M4 add (`held_since` in M2, `monitor.json` in M3, an inherited lineage, `imported` catalog entries, `adopted_from`, a bundle's `origin` and the `external` consistency value in M4) are additive and optional under schema 1, while long-lived instances such as `pg-staging` and `lite-test` live through several tool upgrades. The upgrade suite (§10.3) tests this from M1.
- A Compose or docker CLI bump is always a tool release with its own CI evidence (Compose v5.5 may recreate containers on the first `up` after an upgrade).

### 3.6 Version gate (tiers, no override)

Each release embeds `tested.json`, generated by CI from the lanes that passed: Engine major.minor × architecture with the bundled CLI and Compose, added as the final layer of the image the lanes tested ([ADR-0029](adr/0029-tested-image-and-tested-json-layer.md)). v0.x starts with Engine 24.0 (CI lane on upstream `docker:24.0.2-dind`, the Engine and API floor) and 29.x (the current upstream line) on `amd64`, and adds `arm64` only for the combinations its lane passes (§10.1). These upstream lanes are the evidence for support tier 1 (§11.1). A vendor-built Engine (support tier 2) can differ from the upstream build in kernel, storage driver, cgroup version, logging driver and security options (Synology's build of Engine 24.0.2 does: §11.2), so upstream dind evidence alone never certifies it.

The gate tiers below (0, 1, 2) say which commands may run; they are not the support tiers of §11.1.

| Gate tier | Commands | Platform required |
|---|---|---|
| 0 | read-only commands (`status`, `doctor`, `ps`, `logs`, `bundles`, `validate`, `plan`) | any reachable local daemon |
| 1 | online `backup` and `verify` (hash plus verify tasks) of an instance whose manifest declares `online_backup` | untested Engine allowed when API ≥ 1.43; a warning is recorded in the operation and `status` shows attention |
| 2 | everything else, including drills, restore, deploy, start/stop, `resume` and `abandon` (so an operation interrupted by a platform update waits for the new certification), prune, purge, tasks | the combination is in `tested.json` **and** a host certification exists for the host's platform build: the OS or appliance release (update level included), the Engine build as `docker version` reports it (Engine version, Git commit and build time, containerd and runc versions), kernel, storage driver and architecture, as detected facts, never a platform name. It is a committed platform certification embedded in the release (`support/hosts/`), or a local `selftest --host` `PASS` for the same build in `host/certifications/` (any `PASS` of that build counts; a later `FAIL` does not withdraw it). Retention is in this tier: a `scheduled backup` on a platform that fails it backs up and skips its retention with a recorded warning |

Without a matching certification `status` shows `uncertified` attention and gate tier 2 refuses; any platform update (an OS or appliance update, an Engine update that changes what `docker version` reports, a new kernel or storage driver; on a Linux host every kernel update, once the host has rebooted into it) therefore stops gate tier 2 until `selftest --host` certifies the new build, while gate tiers 0 and 1 (nightly online backups) continue. Drills are gate tier 2, so a scheduled drill refuses with exit 2 until then. The rule is the same on every host, so the gate never needs to tell a vendor build from an upstream one. `selftest --host` itself is allowed on an uncertified host, because it is how a certification is produced and it touches only its own `ingat-selftest-*` instances: inside the command, gate tier 2 waives only the certification, and only for an instance whose selftest marker names the run that this process drives (the run is registered in memory and removed after its teardown); it still needs a tested Engine line and complete platform build facts. There is no flag or file that widens gate tier 2: a marker left by a killed run waives nothing, and supporting a new Engine line or architecture is a tool release with CI evidence (ADR-0014). Every operation record stores the Engine, API, CLI and Compose versions, architecture, OS or appliance release and tool version.

## 4. Execution model

### 4.1 Processes

| Process | Started by | Lifetime | Holds the instance lock |
|---|---|---|---|
| CLI container (`role=cli`) | wrapper | one command | only for foreground terminal tasks (§4.3) and three short commands that change only tool state, never Docker: `host init` (host lock), `init` (host lock), `secret set` (instance lock) |
| Executor container `ingat-exec-<instance>` (`role=exec`) | CLI, through the socket, `docker run -d --rm --init --network host --stop-timeout 120 --log-driver local` (rotation as in §6.2) with the same mounts, image and environment allowlist | one operation | yes, for the whole operation |
| Host executor `ingat-exec--host` | CLI | one host-scope operation (`selftest`, image prune, self-upgrade) | the host lock |
| Task containers `<instance>-x<seq>-<step>-a<attempt>` (`role=task`) | executor, `compose run --rm --no-deps -T --name … --label …` (no `-T` for `stdin = "terminal"`, §4.3) | one attempt of one step | no (the executor holds it) |

Instance names cannot contain `--` ([`MANIFEST_SPEC.md`](MANIFEST_SPEC.md) §6.1), so `ingat-exec--host`, `<instance>--r<seq>` and `<instance>--t<seq>` can never collide with an instance.

### 4.2 Operations that change Docker run detached (ADR-0005)

Every lock-taking operation that creates, starts, stops or removes a Docker object runs in an executor. The only exceptions are foreground terminal tasks (§4.3). `host init`, `init` and `secret set` take their lock in the CLI because they change only tool state, are short and write atomically.

1. The CLI plans (pure, §5.3), prints the plan, collects approval, and writes the approved plan write-once to `plans/<plan-hash>.json`.
2. The CLI starts the executor. Its container name is a second mutex: Docker refuses a duplicate name, so two operations on one instance can never both start.
3. The executor takes the non-blocking `flock` on `instances/<i>/lock`, checks that no operation is open, re-observes the fingerprint and compares it with the plan. A mismatch closes as `refused-stale` with nothing written to the instance (exit 1). An operation that runs an isolated project then allocates its pool subnet (§7.4) before any instance work.
4. The CLI follows `ops/<seq>-<kind>/progress.log` and `steps.jsonl` and returns the outcome of the run file `host/runs/<run-id>.json`, which the executor writes after it released the lock on every run, a refused one included (exit, code, message, `next`, warnings). If the executor stopped running without one, the CLI returns the operation's `result.json`, or else 4 (`executor-vanished`) and `status` shows the open step.
5. Losing SSH, closing the terminal, SIGHUP, a scheduler timeout or killing the CLI stops only the follower. The operation runs to its end. `ingat attach <i>` re-follows.

### 4.3 Foreground one-step tasks

A task whose `stdin` or `stdout` is `terminal` (for example a password reset that prompts for the new password, or a first-run bootstrap that prints a setup token) runs in the CLI container itself, because its output must reach this terminal and never be captured. It is a one-step operation: the CLI takes the instance lock, journals intent, runs the task container under its deterministic name, and closes. If the CLI dies, the kernel releases the lock and the next command's orphan check (§4.5) handles the task container; `resume` of such an operation runs in the CLI again, on the terminal that runs it.

- `stdin = "terminal"`: `compose run` runs **without** `-T`, attached to the CLI container's TTY, so the app's prompt can turn echo off (a password-reset task reads the password at such a prompt). The command refuses (exit 2) when the CLI has no TTY. A test asserts that the prompt runs with echo disabled.
- `stdout = "terminal"` only: `-T` stays; the output is streamed to the terminal and never captured.
- **During a paused install.** A task the pause allows (for example the SQLite consumer's first-run bootstrap) is journaled as a step of the paused operation, in its `ops/<seq>/steps.jsonl`, under the same instance lock and orphan rules; it does not open a second operation (F5).

### 4.4 Cancellation

- In the follower, Ctrl-C asks "detach or request cancel"; without a terminal, SIGINT and SIGTERM mean detach.
- `ingat cancel <i>` (or the follower) writes `ops/<seq>/cancel`. The executor honours it at the next step boundary and inside wait loops. A cancel before any effect closes the operation `abandoned` (exit 130); after an effect it follows the failure rules with code `cancelled` (exit 3: [`LIFECYCLE.md`](LIFECYCLE.md) §3.2). `cancel` refuses a paused operation, because the file would also end the tasks its pause allows and its resume: resume or abandon it instead.
- **Interruptible steps** (an image pull, a dump into staging, probes, drill steps) are stopped: the executor runs `docker stop -t <grace>` on the step's named task container and waits for it to exit **while still holding the lock**, then observes the step. Killing a `compose run`/`exec` client alone does not stop the server-side process.
- **Atomic steps** (migrate, restore into a generation, generation switch, one deletion item) run until their child returns, bounded only by their declared timeout. On timeout the task container is stopped and the step becomes `unknown`.
- **Signals to the executor.** The executor treats SIGINT, SIGTERM, SIGHUP and SIGQUIT alike: each is a cancel request, honoured as above. It is started with `--stop-timeout 120`, so `docker stop ingat-exec-<i>` gives it two minutes to reach a safe point. An atomic step does not stop for a cancel request; if the timeout expires first, Docker kills the executor and the step is observed on the next command. On a host reboot the daemon's own shutdown timeout cuts this window short; the interrupted step is then observed the same way. The session-loss suite sends each real signal (§10.3).
- `docker kill ingat-exec-<i>` is the documented last resort: the kernel releases the flock and the open step is observed on the next command.

### 4.5 Orphan check

Before `resume`, `abandon` or any new mutation after an executor died, Ingat lists every task container (`role=task`) of the open operation, running or exited, labelled `…ingat.op=<seq>` (F15):

- A **running** one refuses the command (`task-running`, exit 2), printing the exact `docker stop` command, which `status` names as `next`. Ingat never observes or re-runs a step whose task container is alive.
- An **exited** one of the step's current attempt, in one of the instance's own Compose projects, is evidence: its exit code and finish time are journaled as `observe` evidence for its step (the exit map then decides the outcome as if the executor had seen it). A container that was created but never started, or one of an earlier attempt, proves nothing. Only after the journal entry is every such container in the instance's own projects removed, re-proved (same labels) right before removal (F8); one outside those projects is neither evidence nor removed.
- A **missing** one (removed by `--rm` before the exit code was read; spike S14) gives no evidence; the step's own `observe` rule decides (an idempotent re-run, `observe = "schema"`, or `unknown`). An exit code is never assumed. On upstream Engine 24.0.2 and 29.9.0 the removal was observed to be daemon-side (local scratch-dind evidence; Unverified in CI and on the first host), so this is the usual case after a crash.

A redo always gets the next attempt number, so its container name never collides with a leftover. The containers of an interrupted operation's isolated project are its scratch outputs, not orphans: `resume` takes the project down before it redoes a scratch step, and `abandon` runs its `Teardown` ([`LIFECYCLE.md`](LIFECYCLE.md) §3.4). Mutating `exec` steps (which have no container of their own) are allowed only inside isolated projects ([`LIFECYCLE.md`](LIFECYCLE.md) F15); taking the project down ends such a step's process before any redo.

## 5. Modules and layering

### 5.1 Layers

```
cli  ──►  ops  ──►  core (plan, approval, executor, steps, journal)
                      │            │
                      ▼            ▼
              model, policy     adapters (runner, compose, docker, override, git, http_probe)  &  store (fs, locks, state)
              (pure, no I/O)
```

Arrows are the only allowed import direction; a stdlib `ast` test enforces it.

| Module | Responsibility | Budget (lines) |
|---|---|---|
| `brand.py` | Product, CLI, label namespace, environment prefix, default roots. The only place these literals may appear. | 60 |
| `cli/commands.py`, `cli/render.py`, `cli/follow.py` | Command table (class, lock, approval, unattended, foreground), argument parsing, human and `--json` output, exit codes; launching and following the executor | 600 |
| `model/manifest.py`, `model/instance.py`, `model/toml_read.py` | Strict `tomllib` parsing (one typed reader) and semantic validation of `ingat.toml` and `instance.toml` | 600 + 300 |
| `model/templates.py` | The closed template vocabulary and its renderer (argv elements and env values only, never a shell) | 200 |
| `model/records.py`, `model/bundle.py` | Record types (host, instance, deployment, operation, verification), the `bundle.json` format, canonical JSON | 400 |
| `policy/compose_policy.py`, `policy/compose_text.py` | Deny-list over the merged `config --format json` model, plus host-capability checks; raw-text rules over the app's Compose files (§9.5) | 300 |
| `policy/gate.py`, `policy/retention.py` | Version-gate tiers; retention selection | 300 |
| `core/plan.py` | Pure planner framework: inputs plus observed fingerprint give an ordered step list and a canonical hash | 300 |
| `core/steps.py`, `core/tasks.py`, `core/probes.py` | The closed set of step types with `apply`, `observe`, and `undo` or a forward marker ([`LIFECYCLE.md`](LIFECYCLE.md) §3.3) | 600 |
| `core/executor.py`, `core/opening.py`, `core/journal.py` | Lock, opening and joining an operation, intent-before-effect log, resume, abandon, auto-abandon, cancel, orphan check | 600 |
| `core/approval.py` | Plan files, typed confirmations, class D challenge (TTY only) | 200 |
| `adapters/runner.py` | The only `subprocess` user: argv only, allowlisted environment, timeout, own process group, byte-exact stdin/stdout file streams, bounded and redacted capture of text streams with a held-back tail | 400 |
| `adapters/compose.py`, `adapters/docker.py` | Typed Compose and Docker CLI adapters. Query methods are free; mutating methods require an `EffectToken` that only the executor issues inside an open, journaled step. | 600 + 400 |
| `adapters/override.py` | Generates the override YAML from data (§6.2) | 250 |
| `adapters/git.py`, `adapters/http_probe.py` | Bare clone, fetch an exact ref, `git archive` export; tool-side HTTP probe client | 200 + 150 |
| `store/fs.py`, `store/locks.py`, `store/state.py` | `O_EXCL` plus `O_NOFOLLOW` temp files, fsync of file and directory, rename, write-once, no-follow tree walks; flock; state-root layout and atomic record writes. Never `sync(2)`. | 600 |
| `ops/*.py` | init, prepare, deploy, backup, verify, restore, lifecycle, tasks, retention, status/doctor, host, selftest, validate, and in M4 import, including adoption payloads (planners built on `core/plan.py`) | about 2,000 (M1-M3) |

No module exceeds 600 lines (ADR-0021). The M1 code exceeds two row budgets above (runtime lines): the step set, about 830, and `ops/*.py`, about 2,700 for M1 alone; every module stays within 600 lines, and a new row budget needs an ADR.

### 5.2 Boundaries enforced by tests

- Only `adapters/runner.py` imports `subprocess`.
- Only `store/` writes under `INGAT_ROOT` or `INGAT_BACKUPS`.
- Import direction follows §5.1; module budgets hold.
- **Forbidden literals** in `src/` (fixtures and tests may use engine names): `postgres`, `pg_`, `sqlite`, `alembic`, `backend`, `frontend`, `uvicorn`, `node`, and the names of the known consumer apps, which appear nowhere in this public repository (owner decision OD-3) and are therefore not listed here. The T0 forbidden-literal grep reads those names from a CI secret (never committed); a run without the secret, such as a fork, skips that part of the check and reports it as skipped. The brand literals appear only in `brand.py`.
- Tests assert behaviour through the CLI and observable effects (files, Docker inventory, exit codes, JSON), never source text or internal names (the earlier in-house deployment controller's suites asserted source layout and froze it).

### 5.3 Plan purity

Every check runs in a pure plan phase over recorded state plus read-only observation: `docker ps/inspect` by label filter, `compose config`, file reads, `statvfs`, `/proc/meminfo`. Planning never creates a container, image tag, volume, network or file under `instances/`. Anything that creates a Docker object is a step. Planning writes only the content-addressed caches `cache/git/` and `cache/src/` (an export is extracted into a temporary sibling under a per-commit lock, made read-only and renamed in), and renders Compose inputs that need files in temporary files under the CLI container's `/dev/shm`, which it removes again (so does `doctor`'s policy check). Pulling candidate images happens in `prepare` (class B, [`LIFECYCLE.md`](LIFECYCLE.md) §4.2), which writes only content-addressed caches (`cache/`, `instances/<i>/candidates/`, image ledger) that the no-trace rule exempts by name.

## 6. Compose invocation

### 6.1 Contract (ADR-0006)

Every Compose call has this shape and runs from the executor with an empty environment plus `PATH`, `HOME` and `DOCKER_CONFIG=<INGAT_ROOT>/cache/docker-config` (created by `host init`; every command but `version` refuses with exit 2, code `docker-config`, while it is not empty, because a client config can add proxy variables to every container or run credential helpers):

```
docker compose -p <project> --project-directory <export>
  -f <export>/<app compose file>… -f <op>/override.yaml
  --env-file <op>/compose.env [--profile <p>…] <verb> [explicit service list]
```

- `<project>` is the instance name, or `<instance>--r<seq>` / `<instance>--t<seq>` for isolated runs. `-p` overrides any top-level `name:` in the app's file (the PostgreSQL consumer's production file declares its own `name:`).
- `<export>` is the read-only `git archive` export of the deployed commit (`cache/src/<commit>/`), or the instance's `app/` directory for image-sourced apps.
- `compose.env` is rendered by Ingat from declared params. Every value is single-quoted; a value containing `'`, a newline or NUL is refused (spike S6 confirms literal reading).
- `up` always gets `--no-build --pull never` and an explicit service list. Task runs are `run --rm --no-deps -T --name <instance>-x<seq>-<step>-a<attempt> --label …ingat.op=<seq> --label …ingat.step=<n> --label …ingat.role=task` (without `-T` only for `stdin = "terminal"`, §4.3). Dependencies are started by explicit `Up` steps that wait for readiness (`compose run --no-deps` skips `depends_on: service_healthy`).
- The merged model (`config --format json --no-env-resolution`) is rendered with the same inputs and used **only** for the policy check (§9.5) and the fingerprint hash. `--no-env-resolution` keeps `env_file` contents (for example the SQLite consumer's SMTP credentials) out of the model, so the model and its hash never contain a secret; the model itself is never stored in bundles. Ingat never executes from a re-rendered model, because round-tripping `$$` escapes drifts across Compose versions (the earlier in-house deployment controller needed a per-version calibration for it).

### 6.2 Generated override

`adapters/override.py` writes a small YAML subset from data: JSON-quoted scalars plus the `!reset` tag. Example for a live deployment of the PostgreSQL consumer (instance `pg-staging`):

```yaml
# This app declares its own json-file logging on every service, so the override adds none;
# an app that declares none gets driver local.
services:
  db:      {image: "sha256:3f1c…", pull_policy: "never", labels: {"io.github.lisahq.ingat.instance": "pg-staging", "io.github.lisahq.ingat.role": "app"}}
  backend: {image: "sha256:9a0b…", pull_policy: "never", build: !reset null, labels: {…}}
  web:     {image: "sha256:77de…", pull_policy: "never", build: !reset null, labels: {…}}
  migrate: {image: "sha256:9a0b…", pull_policy: "never", build: !reset null, labels: {…}}
volumes:
  postgres_data: {name: "pg-staging_pgdata_g1", external: true}
networks:
  internal: {labels: {"io.github.lisahq.ingat.instance": "pg-staging"}}
  edge:     {labels: {"io.github.lisahq.ingat.instance": "pg-staging"}}
```

It always: pins every service to the recorded image ID with `pull_policy: never` and `build: !reset null` (spike S5; fallback: verify tag → recorded ID immediately before every Compose call and refuse a mismatch); adds the stable identity labels; gives every service that declares no `logging` of its own an explicit `logging` block (`driver: local`, `max-size: 10m`, `max-file: 3`), because the daemon's default driver differs by platform (on DSM it is Synology's `db`: §11.2; spike S5) — the block is a tool constant, so it never changes a config hash between deploys, and changing it is a tool release that recreates services, like a Compose bump; for a step whose task has `stdin` or `stdout = "terminal"`, the op-specific override sets `logging: {driver: "none"}` on that task's service whatever its own `logging` (a `compose run --no-deps` one-off does not recreate the live service, so live config hashes are unaffected); maps each declared volume store to its current generation as an external volume, so Compose can never delete it. For isolated runs it also sets every network `internal: true` and resets its name (`name: !reset null`, so Compose names it `<project>_<key>` and an isolated run can never join a live network), removes published ports with `ports: !reset []`, gives subnet params pool values, maps stores to the isolated generation, adds the op label (an isolated project is new for every operation) and adds the `[holds]` environment ([`LIFECYCLE.md`](LIFECYCLE.md) §5.7).

**Stable config hashes.** Labels are part of Compose's per-service config hash, so the override puts only stable identity on live services: `instance` and `role`. Volumes additionally carry `store`, `generation` and `purpose`, task containers get `op`, `step` and `role=task` from `compose run --label`, which never enters a service's hash. The deployment sequence is recorded only in `deployments/<seq>.json`; a running container is matched to a deployment by image ID plus config hash. Every path the live model references is stable or content-addressed: the rendered app env file is stored as `instances/<i>/env/<sha256>.env`, so its path changes only when its content does. A service's hash therefore changes only when its effective configuration changes: a code-only deploy never recreates PostgreSQL, and a config-only change recreates exactly the changed services (recreate-scope suite, §10.3; spike S5 records which inputs enter the hash).

## 7. On-disk layout, records and locks

### 7.1 Layout

```
/srv/ingat/                             INGAT_ROOT (default; /volume1/ingat in the DSM profile): root:root 0700,
                                        plain POSIX directory on a local filesystem (on DSM never a shared folder)
  bin/ingat, bin/ingat.prev             wrapper
  host.json                             state_schema, engine_id, roots, docker path, DockerRootDir, label namespace,
                                        capabilities (CPU CFS, memory limits), runc, storage-driver, image-store, logging-driver,
                                        cgroup, kernel, architecture, live-restore and security-option facts,
                                        tool image (current, previous), isolation and port pools
  host.lock                             flock: instance creation, host-scope operations (selftest, image prune, self-upgrade) (never unlinked)
  host/images/<image-id>/<instance>-<seq>.json  image ledger, one write-once provenance entry per image and operation:
                                        {refs, digest, commit, release, labels, pulled_by}; references are computed from records
  host/allocations/<kind>-<value>.json  one write-once entry per allocated port or subnet (`port-20090.json`,
                                        `subnet-10.250.0.0_24.json`): {instance, param, purpose, op}; an
                                        isolated run's subnet entry is removed by its teardown
  host/attention.json                   last attention set seen by `scheduled status` (§4.15 of LIFECYCLE.md)
  host/certifications/<stamp>-<kind>.json  host check (`host-check`) and selftest (`selftest`) evidence, write-once
  host/runs/<run-id>.json               the outcome of every executor run, a refused one included (write-once; M1 removes only a selftest run's own)
  plans/<plan-hash>.json                approved or approvable plans (write-once; refused after 24 h; M1 removes only a selftest run's own)
  cache/git/<repo-id>.git               tool-owned bare clones (hooks disabled, fsckObjects, ssh/https, file only for fixtures)
  cache/src/<commit>/                   read-only `git archive` exports (Compose project directory)
  cache/fixtures/<run-id>/              selftest's fixture repositories, the only `file://` sources (ADR-0027)
  cache/docker-config/                  the tool's own Docker client config directory, always empty (§6.1)
  keys/<name>/{id_ed25519,known_hosts}  read-only deploy keys and pinned host keys (0600)
  inbox/                                owner-dropped task input files (0700)
  instances/<name>/
    instance.toml                       owner-edited (0600); Ingat never rewrites it
    lock                                flock file, never unlinked
    record.json                         the only mutable instance file: state, lineage, disposable, current deployment,
                                        generation per store, open op, held_since, next_seq, adopted_from (M4)
    secrets/                            0700: generated or set secret files (mode per manifest); env/<KEY> (0600)
    placeholder/                        empty 0555 directory bound to task_dir params outside their task
    app/                                manifest and compose file for image-sourced apps (owner-provided)
    selftest.json                       selftest instances only: the run that created the instance (LIFECYCLE.md §3.3)
    candidates/<commit>-<refs>.json     prepared candidate (keyed by commit and a hash of its image references):
                                        images, digests, labels check, export path
    env/<sha256>.env                    rendered app env files, content-addressed, write-once (0600)
    deployments/<seq>.json              immutable deployment record (the deployment seq lives only here, never in a label)
    deployments/<seq>/                  snapshot: manifest bytes, compose file hashes, override.yaml, compose.env, app env hash, model.sha256
    ops/<seq>-<kind>/                   plan.json, steps.jsonl, progress.log, result.json, cancel,
                                        artifacts/ (bounded, redacted step outputs and log snapshots, 0600),
                                        stage/ (bundle being built), in/ (private input copies; `in/` and an
                                        empty `stage/` are removed when the operation closes), env/, secrets/ (a
                                        drill's throwaway secrets)
    catalog/<bundle-id>.json            write-once seal record: bundle hash, class, size, created_at;
                                        <bundle-id>.pruned.json is the tombstone retention writes
    verifications/<bundle-id>.json      append-only JSON Lines, one verification record per line (outside the sealed bundle)
    reports/                            recorded read-only task reports, for example an invariant check (0600)
  data/<name>/<store>/g<N>/             bind-store generations (owner/mode from the manifest), marker g<N>.json beside each
/srv/ingat-backups/                     INGAT_BACKUPS (default; /volume1/ingat-backups in the DSM profile): written only
                                        by root, the source of the off-host copy (on DSM a shared folder, read-only for
                                        administrators, the Hyper Backup source)
  <name>/<bundle-id>/                   sealed bundles: bundle.json, SHA256SUMS, payload/<entry>/…, meta/
  <name>/.incoming-<bundle-id>/         a copy in progress (never read as a bundle)
Docker: volumes <name>_<store>_g<N> (live generations), <name>_<store>_t<seq> (drills), ingat-probe;
        labels io.github.lisahq.ingat.{instance,role} on live services, {instance} on networks, {instance,store,
        generation,purpose} on volumes; plus {op} on drill generations and every object of an isolated project,
        and {op,step,role=task} on task containers (§6.2); never a per-deployment value
```

### 7.2 Storage rules (ADR-0008)

- **Containers never read from or write to `INGAT_BACKUPS`.** All task I/O uses `INGAT_ROOT`: stages, private input copies, generations. On DSM this also keeps task containers, which run as fixed uids (for example uid 10001 in both stateful consumers' images), away from the shared folder, whose ACLs override POSIX modes.
- **Only root writes into `INGAT_BACKUPS`**: the executor copies a sealed result into `<name>/.incoming-<id>/`, fsyncs every file and directory, then renames it to `<name>/<id>/` within `INGAT_BACKUPS`. The two roots may sit on different filesystems on any host, and on a DSM Btrfs volume each shared folder is a subvolume, so a rename from `INGAT_ROOT` into it fails with `EXDEV`; publishing is always copy-then-rename inside the backups root, so one path serves every layout.
- **Input copies.** A task that reads a bundle gets a private copy in `ops/<seq>/in/`, hash-verified while copying, owned by the task's effective uid (from the manifest's `user` or the image's `Config.User`), modes `0550`/`0440`. Hashes are re-checked after every step that saw the copy.
- **SQLite and app data stay on local disk.** Bind generations live under `INGAT_ROOT/data/` on a local filesystem (for example ext4, XFS or Btrfs), never on a network share (SMB/NFS), a DSM shared folder or a synchronized folder (SQLite's file locking is not reliable there). Bind mounts ignore the host parent directories' modes, so a `0700` root parent does not block uid 10001 inside the container.
- Certification checks the owner and mode of both roots and that no account but root can write into `INGAT_BACKUPS`, so retention never deletes inside a tree other users can change; on DSM it also checks that `INGAT_ROOT` shows no `+` ACL marker, that `synoacltool -get` is empty and that administrators have read-only access to the share. Ingat never reads or changes ACLs itself. Retention deletes with no-follow, descriptor-relative walks and re-proves each item (F8).

### 7.3 Records

- `record.json` is written by `init` and afterwards replaced atomically under the instance lock, only by the executor (or the CLI running a terminal task) at well-defined points: when it opens an operation, in its `Record` steps ([`LIFECYCLE.md`](LIFECYCLE.md) §3.3) and when it closes one, before `result.json` ([`LIFECYCLE.md`](LIFECYCLE.md) §3.1); unknown fields of the same `state_schema` are carried over unchanged (§3.5).
- Deployment records, plans, catalog entries and results are write-once (exclusive create, fsync file and directory).
- `steps.jsonl` is append-only, one JSON object per line, fsync per line: `{seq, step, phase: intent|done|failed|unknown|cancelled, at, evidence}`. A torn last line counts as never written; that is safe because an intent is fsynced before its effect starts.
- Operation sequence numbers are per-instance and monotonic, never wall-clock based.
- Records carry explicit types; behaviour never depends on resource-name prefixes (deriving behaviour from name prefixes caused a defect in the earlier in-house deployment controller).
- Strict JSON (duplicate keys and NaN refused) and canonical bytes (sorted keys, compact, UTF-8) for every hashed document, in one module.

### 7.4 Locks

- One non-blocking `flock` per instance on a never-unlinked file, held by the executor for the whole operation; a busy lock refuses at once (exit 2) with the holder's op, pid, command, operator and start time from `lock.holder.json` (`host.lock.holder.json` for the host lock). Taking a lock rewrites its holder file, so the no-trace rule exempts both by name (F2).
- `host.lock` is taken first when both are needed (host, then instance). Operations on an existing instance never need it: the shared host files they write (image ledger entries, isolated-run subnet allocations) are per-entry, write-once files created with `O_EXCL`, so there is no read-modify-write of a shared JSON file. An executor allocates an isolation subnet by creating `host/allocations/subnet-<address>_<prefix>.json` exclusively for the first pool `/24` that no allocation entry and no network on the daemon (every network's IPAM config) uses; a lost race moves to the next `/24`, and a pool with no free `/24` refuses at op open (`capacity`). The default pool is `10.250.0.0/20`, outside Docker's built-in default address pools ([ADR-0030](adr/0030-isolation-pool-outside-docker-default-pools.md)); a `host.json` written earlier keeps its recorded pool.
- Read-only commands take no lock; they read atomically replaced files.
- `flock` on a bind-mounted file excludes across containers because they share the host kernel and inode (spike S3).
- Scheduled jobs never wait for or break a lock: a busy lock exits 2 and the scheduler mails the owner.

### 7.5 Naming and identity

- Instance names: `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, at most 30 characters, unique per host. The name is the identity and the Compose project name.
- Each instance has a random 128-bit `lineage` id, created at `init` and copied into every bundle. A restore into a new instance inherits the bundle's lineage (Planned M4, together with the `single_active` check).
- Engine binding: `host init` records the daemon's engine ID; a mismatch refuses every mutation until `ingat host rebind` (class D, Planned M4), which first checks for foreign resources.
- Ownership: an object is owned only when it carries the Ingat instance label **and** (for containers) the matching `com.docker.compose.project`. A project label without the Ingat label is a `foreign` blocker; a volume or network used by any non-owned container is `shared` and never deletable (the same classification as the earlier in-house deployment controller's). Docker cannot change the labels of an existing object, so a foreign object never becomes owned: adoption (M4) moves a foreign deployment's data into a new instance through a payload the owner produced with the app's own backup command, and Ingat never touches the foreign project ([`LIFECYCLE.md`](LIFECYCLE.md) §4.16).

## 8. Templates

Manifest argv elements, env values and paths use a closed template vocabulary ([`MANIFEST_SPEC.md`](MANIFEST_SPEC.md) §3). An unknown variable is a validation error; there are no expressions; rendered values are checked for NUL and newlines and are never passed to a shell.

## 9. Security and trust model

### 9.1 Trust anchors

The pinned image (digest, or a checksum-verified tarball's image ID), the root-owned wrapper, the root-only `INGAT_ROOT`, owner-approved git refs resolved once to a 40-hex SHA, and the engine ID recorded at `host init`. There is no self-verifying bootstrap; upgrades are image swaps.

### 9.2 What Ingat defends against

Mistakes (wrong instance, stale plan, unintended deletion, an unreviewed destructive step), crashes and interruptions, untrusted inputs (app repository content, backups, other Docker objects on the daemon), and secret leakage. It does not defend against root.

### 9.3 Docker socket

Mounted only into the CLI and executor containers (ephemeral, no listener). Task, probe and app containers never get it; the policy refuses socket binds.

### 9.4 Secrets (ADR-0019)

- Generated at `init` with `secrets.token_*` (32 characters `[A-Za-z0-9]`, pairwise distinct per instance) or set with `ingat secret set <i> <KEY>` reading stdin, never argv. Never regenerated by upgrade, restore or rollback.
- Compose file secrets live in `instances/<i>/secrets/` (0700) with the manifest's mode (for example 0444 for a secret file that a non-root uid reads through the bind mount). Env-file secrets (for example the SQLite consumer's SMTP password) live in `secrets/env/<KEY>` (0600) and are rendered only into the deployment's `app.env` (0600).
- Before every Compose call each secret path must be a regular, non-empty file; a directory at a secret path is refused, never repaired (Compose silently creates one). The planner checks every Compose file secret a model binds; the executor checks each variant's secret files with no-follow `lstat` (no link in any component) right before every call that creates a container (`Up`, `RunTask`, an undo's `up`), else the step fails `secret-file` before any effect.
- Never in argv, plans, records, bundles, logs or errors; errors name keys and positions only (an earlier in-house deployment controller leaked a secret this way). Records carry the hash of the non-secret env projection plus secret key names only.
- The runner redacts every secret value of the instance (a file secret also without its final line break) and its URL-encoded form in **text captures** only (`json`, `record`, stderr, progress, log snapshots), with a held-back tail as long as the longest secret (a technique proven in the earlier in-house deployment controller's runner).
- `file:` and `bundle:` streams (task stdin and stdout, for example a `pg_dump` archive) are byte-exact: never redacted, truncated or bounded, so a backup is never corrupted. Payload bytes are the app's data; Ingat never writes a secret into them.
- Output classified `terminal` (setup tokens) is never captured or journaled, and no logging driver writes it (the `none` driver: §3.3, §6.2); log snapshots skip a service during the install window that prints a token.

### 9.5 Compose model policy (deny-list over the merged model; `policy/compose_policy.py`)

Refused: `privileged`; any `cap_add`; `devices`, `device_cgroup_rules`; `host` for `network_mode`, `pid`, `ipc`, `uts`, `userns_mode` or `cgroup`, and `container:<x>` for any of them (it joins a container outside the project: F8), while `service:<x>` must name a service of the same model; any other `network_mode` than `none`, `bridge` or `service:<x>`, and in an isolated run than `none` or `service:<x>` (`bridge` would skip the internal networks: F13); every `security_opt` entry except `no-new-privileges` (bare or true) and `apparmor=docker-default` (a false `no-new-privileges`, any `seccomp` entry, `builtin` included, and every `label` option replace or relax a daemon-wide confinement); `cgroup_parent`; `container_name`; `volumes_from`; `external_links`; `runtime`; `use_api_socket` (Compose would bind the Docker socket into the service: §9.3); mount types other than `bind`, `volume` and `tmpfs`; app-declared `external` volumes or networks; `driver_opts` on volumes and networks; a network driver other than `bridge`; app labels in the Ingat namespace; any bind of `/var/run/docker.sock`, `/run/docker.sock` or `/`; bind, `env_file`, secret or config sources outside the instance's store generations, task dirs, placeholder, secrets directory and rendered env file (read-only binds and config files inside the export are allowed); a `label_file` outside the export (Compose reads it into the labels at every call); published ports on any address other than `127.0.0.1` (no consumer needs one; a non-loopback port needs an ADR); named volumes that are not declared stores; `build` contexts outside the export. Also refused, because each reaches around one of the rules above: `provider` services (Compose would run an executable the app names, inside the executor that holds the Docker socket: §9.7), `privileged` lifecycle hooks (`post_start`, `pre_stop`), GPU requests (`gpus`, `deploy.resources.reservations.devices`), a network with a fixed `name:` (Compose joins an existing network of that name, which acts like `external`), and interpolation variables named `COMPOSE_*` or `DOCKER_*` (Compose reads its own settings, such as `COMPOSE_REMOVE_ORPHANS`, from the `--env-file`; refused as param names by manifest validation and again by the Compose adapter).

**Raw-text rules** (`policy/compose_text.py`). The merged model never shows `include` and `extends` files, and Compose reads them before any model rule runs (remote OCI and git includes are fetched during `config`) and again at every call, so their content could change after the check. Before any Compose call reads an app's Compose files (in `prepare` and `deploy`, and in `validate`), the text of each runtime and build file must pass: only the top-level keys `version`, `name`, `services`, `networks`, `volumes`, `secrets`, `configs` and `x-*` (so no `include`); every `extends` names only a service of the same file; and what the line rules cannot read for certain is refused too (a document that does not start at column 0, a top-level flow mapping, explicit or alias keys, escaped double-quoted keys, `!!` or verbatim tags, tabs in indentation, control characters and Unicode line breaks). A refusal is `unsupported-source`.

Refused when the host lacks the capability (`host.json`, recorded by `host init` from the typed `CpuCfsQuota` and `CpuCfsPeriod` fields): a non-zero `cpus` limit (`deploy.resources.limits.cpus` or `cpus`) when the daemon reports no CPU CFS quota support, because the daemon then refuses the container create (NanoCPUs), so a create can never fail half-way through an operation. The message names the service, the key and the param that sets it. Docker silently discards unsupported blkio limits with a warning, so there is no blkio check; an app that needs I/O limits adds one by ADR. Such hosts exist: DSM 7.4.1 with Container Manager 24.0.2-1706, the first platform profile, reports no CPU CFS quota support (§11.2), and the PostgreSQL consumer sets `cpus` on every service through params: its instances on such a host set those params to `"0"`, and if spike S11 shows that `cpus: "0"` is not "no limit", the app removes its `cpus` keys in its own repository.

Allowed (privilege-lowering): `read_only`, `cap_drop`, `user`, `tmpfs`, `init`, `security_opt: no-new-privileges` (and `apparmor=docker-default`, the daemon's own default), resource limits, `shm_size`, `stop_grace_period`, `network_mode: none`, internal networks, Compose profiles, long bind syntax. The hardened Compose files of both stateful consumers pass unchanged; the earlier in-house deployment controller's allow-list envelope rejected both.

### 9.6 Git

Read-only deploy key per repository; `known_hosts` pinned at `init`; a tool-owned bare clone with `core.hooksPath=/dev/null`, `transfer.fsckObjects=true`, `protocol.allow` limited to ssh and https (plus `file` only for fixture repositories under `INGAT_ROOT/cache/fixtures/`, [ADR-0027](adr/0027-local-fixture-repositories.md)), `gc.auto=0`; refs resolved once to a full SHA; export by `git archive` into a temporary directory that is made read-only and then renamed. Submodules, LFS and symbolic links in the exported tree are refused (a link would let a read-only bind inside the export reach any host path), and so is an export whose manifest differs from the bytes validated through `git show` (a `.gitattributes` `export-subst` or `export-ignore`). Ingat builds no images ([ADR-0026](adr/0026-app-images-built-in-app-ci.md)).

### 9.7 Never allowed (no override exists)

Compose passthrough of `up/down/run/exec/build/rm` (named refusals print the managed command); `down -v`, `docker system|volume|image|network prune`; deleting an object that is not proved owned and listed in a closed plan; stopping, starting, exec'ing into, mounting, relabelling, restoring into or deleting a foreign object (adoption works only from a payload the owner produced: ADR-0024); restoring over current data; migrating without a sealed pre-change bundle; executing anything from a bundle; host executables named by a manifest; restoring secrets or configuration from a bundle; any Docker endpoint but the local socket; rootless or remote daemons; silently falling back to another Compose or docker binary; following symlinks in tool-owned trees; global `sync(2)` (it hung the earlier in-house deployment controller); `--force` or `--yes`; auto-update.

## 10. Testing and certification

### 10.1 Tiers

| Test tier | Runs | Content | Budget |
|---|---|---|---|
| T0 static and unit | every push | ruff, mypy strict, import-direction and module-budget lints, forbidden-literal grep, `subprocess` only in the runner; pure tests of manifest/instance validation, templates, policy, plan hashing, retention, journal replay, redaction | < 2 min |
| T1 real Docker (the gate) | every push | GitHub Actions `ubuntu-24.04` (`amd64`), privileged `docker:24.0.2-dind` (upstream Engine 24.0.2: the Engine and API floor, 1.43, and the Engine line of the first platform profile; not Synology's build, which only host certification covers) and `docker:29.Y.Z-dind` (one exact tag in `image/versions.lock`); the arm64 lane on the GitHub-hosted arm64 runner `ubuntu-24.04-arm` with the same 29.Y.Z tag (today 29.9.0). Each lane loads the tool image that one job of the pipeline built once, in its own architecture's variant ([ADR-0029](adr/0029-tested-image-and-tested-json-layer.md); spike S13), runs the unit suite inside it and the real-Docker modules in parallel processes, each on its own scratch host, with the named crash cases; it also runs the M0 spike script, whose items never change the lane's verdict | < 15 min per lane (target; the real-Docker modules alone took about 15 min on local scratch daemons, so the CI lane timeout is 45 min until CI timings exist) |
| T2 nightly | nightly | full generated crash matrix (every crash point of every M1 plan) on the amd64 lanes; cross-host restore on two dind daemons (M4); the adoption suite (M4). Consumer conformance runs in each app repository's nightly job, never in the tool's CI | < 2 h |

The upstream dind lanes are the evidence for support tier 1 (upstream Engine on Linux, §11.1). The arm64 lane runs from M1 (GitHub-hosted arm64 runners are free for public repositories; spike S13 confirms it in M0). arm64 support is claimed only after that lane passes: until then `tested.json` has no arm64 entry and gate tier 2 refuses on an arm64 host. An arm64 host on Engine 24.0 stays at gate tiers 0 and 1 until a `docker:24.0.2-dind` arm64 lane is added by a tool release.

### 10.2 Fixtures (no app repositories needed)

`fx-web` (stateless static server), `fx-lite` (the tool image in fixture mode, mirroring the SQLite consumer: a small HTTP server with SQLite WAL, files, a fake outbound queue honouring its `JOBS` and `DELIVERY_MODE` keys ([`MANIFEST_SPEC.md`](MANIFEST_SPEC.md) §11) that writes "sent" markers, and app-native migrate/backup/restore commands with a held-queue restore), `fx-pg` (`postgres:16` as the data service plus a shell app mirroring the PostgreSQL consumer's two-container hooks, with an init-server readiness race, and a web service that refuses to start without a default IPv4 route unless a hold sets its trusted proxy address, as the PostgreSQL consumer's web service does).

### 10.3 Required suites (behaviour through the CLI only)

- **Lifecycle loop**: init → deploy → backup → verify --restore-test → update → restore → backup → update, on `fx-pg` and `fx-lite`, on both engines.
- **No trace**: every refusal path (including `refused-stale` inside a started executor), every `--plan` and every read-only command leaves the `instances/` tree hash and the labelled Docker inventory identical after exit, with no container/volume/network/image create, destroy, start, stop or die events in the window except those of the command's own `role=cli` and `role=exec` containers (both `--rm` and labelled) and `exec` events of declared read-only probes.
- **Crash matrix**, generated from each operation's step list: SIGKILL of the executor before and after every intent and done record (via the test-only hook), and in the middle of every task step while its task container runs. Then `status --json`, run its `next` command, and assert convergence: no data lost, the previous generation intact, no unlisted deletion, and the printed command succeeds. Named cases: the executor killed during an online backup task, after which the next `scheduled backup` auto-abandons it and succeeds; the executor killed mid-task, after which `resume` records the exited task container's exit code, removes it and succeeds (the daemon normally removes such a container itself, §4.5, so the suite plants one); an install paused, an allowed task run and journaled in the paused operation, then `resume`; a restore into a never-deployed instance killed after its generation switch, which `next` (`restore` again) converges from the deployment recorded before the start ([`LIFECYCLE.md`](LIFECYCLE.md) §4.10).
- **Session loss**: killing the CLI or follower (SIGHUP, SIGTERM, kill) never stops the executor; real SIGINT, SIGTERM, SIGHUP and SIGQUIT sent to the executor each act as a cancel request; a cancel request stops at the next boundary; a task container is never orphaned past the lock.
- **Recreate scope**: a code-only deploy of `fx-pg` keeps the data-service container ID; a config-only change recreates exactly the changed services.
- **Upgrade** (from M1): install release N-1 (the previous tag, or the previous main commit before the first tag), create an instance and leave an operation open; the upgrade to N refuses; close the operation, upgrade, read the N-1 state with N; then run `bin/ingat.prev` (N-1) and read the state N wrote.
- **Readiness**: on `fx-pg`, no task touches the store before the stable TCP probe passes (init-server race).
- **Generation safety**: no live writer ever mounts an unswitched generation, and no isolated project ever mounts the live generation.
- **Isolation**: a `fx-lite` drill and restore produce zero sent markers; a restore ends `held`; the `fx-pg` web service starts in isolation only through its hold (an internal network may have no default route: spike S12).
- **Foreign resources**: a hand-made container in the same project, a foreign container using an instance volume, a same-name volume created after the plan, a foreign network whose IPAM uses a pool subnet: each refuses or is skipped.
- **Adoption** (M4): hand-made foreign `fx-pg` and `fx-lite` projects (started with plain `docker compose`) are quiesced and exported by the test with plain `docker` and the fixtures' own backup commands, as the runbook says ([`LIFECYCLE.md`](LIFECYCLE.md) §4.16), then `import --payload`ed into new instances, drilled, restored, backed up and updated; Docker events show no event on any foreign object caused by an Ingat container; every refusal (a payload with links, special files, unlisted or several top-level entries, a payload name that breaks the payload rule, an instance that is not `registered`, a release without a prepared candidate, a restore of an imported bundle that is not `restore-tested`) leaves no trace.
- **Secret canary**: seeded values never appear in any text output, record, log snapshot, plan or in a bundle's Ingat-written files (`bundle.json`, `SHA256SUMS`, `meta/`); a payload file that contains a seeded value stays byte-identical in the bundle; a terminal task's seeded token appears in no file under the Docker root.
- **Terminal tasks**: a `stdin = "terminal"` task runs with echo disabled and refuses without a TTY.
- **Version gate**: an untested Engine refuses gate tier 2 with exit 2 and allows gate tier 1 with a recorded warning.
- **Policy table**: hostile snippets refused; hardened fixture Compose files (`read_only`, `cap_drop`, loopback ports, file secrets, `cpus` params) accepted.

### 10.4 Host certification (owner-run)

A host certification is evidence that the tool works on one platform build: the OS or appliance release (update level included), the Engine build as `docker version` reports it (Engine version, Git commit and build time, containerd and runc versions), kernel, storage driver and architecture, as detected facts (§3.6). The Engine package build (on DSM the Container Manager build) is a `facts.sh` field of the committed file and of its file name, not a gate key, because the tool container cannot see it. After any change of that build, `ingat selftest --host` (steps 2-3, minutes) re-certifies it for the gate. On a support-tier-1 host that is all: CI ran the full suites on upstream builds of its Engine line (§10.1), and the local `selftest --host` covers the host's own build, a distribution package included. A support-tier-2 platform also needs the full checklist (steps 1-5, about 30 minutes) and a newly committed `support/hosts` file for each new platform release line or vendor package build that changes the Engine, containerd or runc (on DSM: a new DSM minor line, or a Container Manager build that changes them), because no CI lane reproduces a vendor engine. The first support-tier-1 host also runs the full checklist once (M4 slice 12), so the generic Linux install path and schedulers have host evidence. A tool release needs no host certification of its own (CI covers the tool); the upgrade on each host runs `selftest --host` with the new version before it replaces the wrapper (§3.5).

1. `facts.sh` (read-only, host side): `/etc/os-release` and, where present, the platform's own release file and package builds (on DSM `/etc.defaults/VERSION` with version, build and update level, and the Container Manager build), `docker version` (Engine, containerd, runc), `docker info` (CPU CFS, memory-limit and blkio support, storage driver, default logging driver, cgroup version, live restore, security options), `uname -m/-r`, `ldd --version`, `/proc/meminfo`, filesystem type and layout of each root (Btrfs subvolumes where present), free space of each root and the Docker root, `ls -ld` of both roots, socket mode, and the ACL facts where the platform has ACLs (on DSM `synoacltool -get` of both roots and the `ingat-backups` share permission, administrators read-only).
2. `ingat host check` (it writes only its certification) records the same facts as seen from the tool, the host risks and the build keys changed since `host init` into `host/certifications/<stamp>-host-check.json`, with result `PASS`, `FAIL` (a root or the tool's Docker client directory is wrong) or `BLOCKED` (a platform build fact is missing); anything but `PASS` exits 5.
3. `ingat selftest --host` runs the lifecycle loop on disposable `ingat-selftest-*` instances of `fx-lite` and `fx-web` (from fixture repositories it creates: ADR-0027), then tears them down through the closed deletion path, and writes `host/certifications/<stamp>-selftest.json`: `PASS` only when every check passed and the teardown left nothing.
4. Manual checklist: a scheduled run through the host's scheduler with failure mail (a systemd timer with `OnFailure=`, a cron entry, or DSM Task Scheduler); an SSH drop during a backup; the off-host copy picking up `INGAT_BACKUPS` (restic, borg or rsync on Linux; Hyper Backup on DSM); after a platform update, the wrapper and state still present.
5. The owner commits `support/hosts/<platform release and update>-<engine package build>-<kernel>-<arch>.json` to the tool repository (on DSM: `<dsm build and update>-<container manager build>-<kernel>-<arch>.json`). It names only the platform software and architecture (OS or appliance release and update level, the Engine package build such as the Container Manager build, the Engine version, Git commit and build time, containerd and runc versions, kernel, architecture such as `x86_64` or `aarch64`), never a device model (NAS, server or board), a CPU model, a hostname, address or instance path, or details of the unit such as its RAM, free space or volume layout (owner decision OD-3); those stay in the host's own `host/certifications/` evidence. It lists host risks the facts show (for example runc older than 1.1.12, or no seccomp). Support claims list only certified combinations plus the CI matrix.

## 11. Hosts and support matrix

Ingat runs on one host with a local Linux Docker Engine 24.0 or later and Compose v2, on any distribution or appliance: a bare-metal server, a VM or VPS, a NAS that offers Docker (Synology or any other vendor), a small board. Platform differences are handled as detected capabilities (§11.2) and by a certification per platform build (§3.6, §10.4), never by branching on a platform name, vendor or model (§11.3). The first real deployment is a Synology NAS on DSM 7.4.1 with Container Manager 24.0.2-1706; its traits, observed by a read-only probe and by platform research on 2026-10-14, form the first platform profile (§11.2). They are traits of that DSM and Container Manager release, not of a device model. Where they conflict with an earlier assumption, the observation wins. Nothing of Ingat has run on any host yet.

### 11.1 Support matrix

Support tiers say which hosts Ingat supports and what evidence each needs; they are not the gate tiers of §3.6. Minimum requirements for every host: §11.4.

| Support tier | Hosts | Evidence required | Status |
|---|---|---|---|
| **Support tier 1** | Linux hosts on any distribution (bare metal, VM, VPS or a board) running upstream Docker Engine (docker-ce from Docker's repositories, or a distribution package) on an Engine line that CI tests (today 24.0 and one exact 29.x), on `x86_64`, or on `aarch64` for the lines the arm64 lane passes (29.x only) | The upstream dind lanes (§10.1) plus a local `selftest --host` certification of each platform build (§10.4) | Covered by the CI lanes from M1; the first committed generic Linux certification (VPS or server) is Planned M4 slice 12. An upstream Engine 24.0 or later on a line without a CI lane runs gate tiers 0 and 1 only, until a tool release adds the lane |
| **Support tier 2** | Vendor-built engines on appliances: Synology Container Manager first (the DSM profile, §11.2); other vendors' appliances later, each through its own platform profile | A platform profile: the full certification checklist and a committed `support/hosts` file for each platform build line, plus a local `selftest --host` after every update (§10.4) | Synology DSM 7.4 with Container Manager 24.0.2 on `x86_64`: the first real deployment. No certification exists yet; the first is an M1 exit-gate item |
| **Not supported in v1** | Rootless Docker; Docker Desktop on Windows or macOS for production use (development only); Podman; Kubernetes or Swarm; multi-host setups; Docker Engine older than 24.0 (API below 1.43), which also excludes Synology DSM 7.1 and earlier with the legacy Docker package (Engine 20.10, API 1.41, Compose v1) | — | No tier, CI lane or certification will be added in v1. DSM 7.1 is also out of extended life since June 2025, so no further fixes are expected (platform research, 2026-10-14) |

Support claims name only tested combinations: an Engine line and architecture whose CI lane passed, plus a certification of the platform build.

**Loss of the host.** Recovery needs a replacement certified host of either support tier: for example a Linux server or VPS, or another Synology NAS on a certified DSM and Container Manager build (a host on DSM 7.1 or earlier cannot be one). Procedure: install, certify, recover the bundles from the off-host copy, `import` them, and restore them into instances initialised from the owner's offline encrypted copy of instance configs and secrets (owner decision OD-9; [`LIFECYCLE.md`](LIFECYCLE.md) §5.9; runbook in M4 slice 10, rehearsed on the first host at the M4 exit gate).

### 11.2 Platform traits and what they change

Ingat handles every platform difference as a fact that `host init` and `host check` record (§3.4) and that the planner, the override and the gate use. A platform profile is documentation and certification data (install values, observed traits, operator rules), never a code path (§11.3).

| Trait | Detected from | What Ingat does |
|---|---|---|
| CPU CFS quota/period | `docker info` (`CpuCfsQuota`, `CpuCfsPeriod`) | Without it the daemon refuses a create with a non-zero `cpus` limit, so the plan-time capability check refuses any non-zero `cpus` (§9.5); an app that sets `cpus` exposes it as a param, and its instances on such a host set it to `"0"` |
| blkio throttle | nothing to detect | Docker silently discards unsupported blkio limits with a warning and no consumer sets them, so there is no check; an app that needs I/O limits adds one by ADR. Memory limits and `cpu_shares` stay available |
| Default logging driver | `docker info` | Never relied on: services without their own `logging` and the executor get `local` with rotation, and the CLI and terminal tasks get `none`, so a terminal secret is never written by a logging driver (F12; §3.3, §6.2) |
| Storage driver | `docker info` | Never depended on; a change is a new platform build that needs re-certification, because it hides existing images and containers (risk R14). The upstream dind lanes use overlay2 |
| Image store (classic or the containerd snapshotter) | `docker info` (`DriverStatus`) | Recorded by `host init`. Image IDs differ by store (with the containerd store, which the local upstream 29.9.0 dind daemon used, an ID is the index digest), so Ingat takes IDs only from `image inspect` on the host's own daemon and matches containers by the image ID they run, never by a Compose label |
| cgroup version | `docker info` | Recorded for the certification; no Ingat feature needs a particular cgroup version |
| Kernel | `uname -r` | Part of the platform build; app images pass a canary on the host's kernel before an app is declared supported there (§11.3 item 6) |
| Architecture | `docker info`, `uname -m` | Docker pulls the matching variant of the multi-arch image; `tested.json` and certifications are per architecture; app images must exist for it |
| Live restore | `docker info` | When off (the upstream default), a daemon restart stops every container and an open operation becomes `interrupted` (resumable), so the Engine is updated deliberately, never automatically |
| Security options (seccomp, AppArmor) | `docker info` | Recorded; the certification lists missing seccomp as a host risk (weaker isolation), mitigated mainly by trusted, digest-pinned images |
| runc version | `docker version` | Recorded; a runc older than 1.1.12 (CVE-2024-21626) is listed as a host risk |
| Engine and API version | `docker version` | Gate tiers (§3.6); healthcheck `start_interval` needs Engine 25, so no app may depend on it while the floor is 24.0 |
| A vendor container GUI | not detectable | Operator rule: never use a GUI's project actions on an Ingat project; `status` and `doctor` report `changed-outside` ([`LIFECYCLE.md`](LIFECYCLE.md) §4.15) |

#### First platform profile: Synology DSM 7.4 with Container Manager 24.0.2 (support tier 2)

**Observed traits** (DSM 7.4.1 with Container Manager 24.0.2-1706): Synology's build of Engine 24.0.2 (API 1.43), containerd 1.7.1, runc 1.1.7; the host's own Compose plugin v2.20.1 (unused by Ingat); a vendor kernel, 4.4.x on many DSM 7.x platforms (some newer platforms run 5.10); cgroup v1; AppArmor without seccomp; no CPU CFS quota/period; no blkio throttle (Docker discards blkio limits with a warning); default logging driver `db`; live restore off; a storage driver that depends on the volume filesystem (aufs on ext4 volumes, btrfs on Btrfs volumes); Snapshot Replication only on Btrfs volumes; host Python 3.8 (system) and 3.9 (package), unused; Docker access only as root (`sudo -i`); DSM Task Scheduler for scheduled jobs. **Install values:** roots `/volume1/ingat` and `/volume1/ingat-backups` (a shared folder, the Hyper Backup source), docker at `/usr/local/bin/docker` (§3.4).

How the generic rules apply to this profile:

- **Logging.** Container Manager's default driver is Synology's `db`. Terminal tasks and the CLI container log to the `none` driver, so a terminal secret is never written by any logging driver (F12); the executor and services use `local` with rotation (§3.3, §6.2), so `ingat logs` and `SnapshotLogs` read a standard driver and logs rotate. Container Manager's log view may show less for Ingat projects.
- **CPU and I/O limits.** No CPU CFS quota/period support (observed on DSM 7.4.1 with Container Manager 24.0.2-1706; it was spike S11): the daemon refuses a container create with a non-zero `cpus` limit, so the plan-time capability check refuses any non-zero `cpus` on a host whose `host init` recorded no CPU CFS support (§9.5); an app that sets `cpus` exposes it as a param, its instances set that param to `"0"`, and the app drops its `cpus` keys only if S11 shows that `"0"` is not "no limit". No blkio throttle: Docker silently discards unsupported blkio limits with a warning, and no consumer sets them, so there is no blkio check. Memory limits and `cpu_shares` remain available.
- **Storage and recovery.** The storage driver depends on the volume filesystem (aufs on ext4 volumes, btrfs on Btrfs volumes), and Ingat must not depend on it. Snapshot Replication exists only on Btrfs volumes, so recovery never relies on snapshots: it rests on Ingat's sealed bundles in `ingat-backups` plus the owner's Hyper Backup copy off the NAS ([`LIFECYCLE.md`](LIFECYCLE.md) §5.9). Volume generations live inside the Docker root (`@docker` on the volume where Container Manager is installed, for example `/volume1/@docker`; not a shared folder), which Hyper Backup cannot select, so a live store is never a recovery source. The upstream dind lanes use overlay2, and upstream dind cannot run aufs at all (upstream Docker removed the aufs driver in Engine 24.0; it survives only in Synology's build), so the storage-driver behaviour of a DSM host is covered only by host certification (risk R14).
- **runc 1.1.7.** Container Manager 24.0.2-1706 ships runc 1.1.7, which predates the fix for CVE-2024-21626 (runc 1.1.12). `host check` records the runc version and the certification lists the exposure as a host risk. The main mitigation is running only trusted images (built from the owner's repositories or official images, pinned by ID and digest); services publish only on `127.0.0.1` behind the DSM reverse proxy. LAN-only exposure of the NAS is recommended: CVE-2024-21626 is triggered by a malicious image or exec working directory, not by network reachability, but a compromised internet-facing container would meet weak isolation (runc 1.1.7, no seccomp, an old vendor kernel). A Container Manager build with a fixed runc closes the risk (after re-certification).
- **Container Manager GUI.** A project's "Clean" runs a Compose down that removes its containers, networks, volumes and images; "Delete" removes the project's data. Whether Container Manager lists and can Clean an Ingat-created project, and whether Clean removes external volumes, is Unverified; the operator rule applies either way: never use Container Manager's project actions on an Ingat project; Ingat cannot prevent it. `status` and `doctor` report `changed-outside` attention when a deployed instance's containers, networks or generation volumes are missing or differ from the recorded deployment ([`LIFECYCLE.md`](LIFECYCLE.md) §4.15). Keep Container Manager auto-update off (and DSM's automatic update installation, if enabled) and update deliberately: live restore is off, so a daemon restart stops every container and an open operation becomes `interrupted` (resumable).
- **Version gate.** A DSM update, or a Container Manager update that changes the Engine build, changes the certified build: gate tier 2 refuses until `selftest --host` certifies the new build (§10.4), scheduled drills included, while nightly online backups (gate tier 1) continue (§3.6). Install the newest DSM update before a host's first certification so that the certification covers it. DSM 7.4 reaches end of maintenance about June 2028 with no extended life, so a move to the next DSM line comes before then and is a re-certification (risk R13).
- **Kernel.** Many DSM 7.x platforms run a 4.4.x kernel (some newer platforms run 5.10). A 4.4 kernel is below Node.js 24's Tier-1 minimum (4.18), so spike S15 runs the apps' images on a DSM 4.4 kernel before they are declared supported (the SQLite consumer's runtime and the PostgreSQL consumer's web build stage use Node 24). The observed release runs cgroup v1 (v2 needs kernel ≥ 4.15).
- **Host tools, root and scheduling.** The host's Compose plugin v2.20.1 and host Python 3.8/3.9 are never used. Docker needs root, reached over SSH with `sudo -i`. DSM Task Scheduler runs the scheduled jobs ([`LIFECYCLE.md`](LIFECYCLE.md) §7; `schedule render --dsm`, Planned M3).
- **Unchanged by the traits.** Engine 24 pulls zstd-compressed layers (Engine ≥ 23), so no forced-gzip rule is needed (that was a concern of the legacy Docker package's Engine 20.10 only); Ingat's own image runs on the x86-64 baseline, and an app image that needs a higher x86-64 level is caught by its canary (§11.4). Whether a host's RAM holds its live instances plus a drill is Unverified until `facts.sh` records `MemAvailable` with those instances running. Drills refuse on `[drill] min_free_memory` and never rely on swap.

### 11.3 Generality rule

A new app must not need a core change. It fits the manifest schema, the closed sets of step types, task modes and probe kinds, and the onboarding checklist below, or the gap is recorded by ADR as a generality failure (ADR-0021). The rule extends to hosts: platform differences are capabilities that `host init` and `host check` detect and the planner, the override and the gate check, plus a certification per platform build (§3.6, §10.4); no code path branches on a platform name, vendor, model or an app name. A platform profile (§11.2) is documentation and certification data, never a code path. A platform whose differences cannot be expressed as detected capabilities is a generality failure, recorded by ADR.

**Onboarding checklist for a new app.** An app is ready for Ingat when its repository provides:

1. **Compose files** with **stable service names** (they name tasks, roles and config hashes; renaming a service is a topology change); published ports only from `port` params on `127.0.0.1`; named volumes only for declared stores; no `container_name`, host networking, privileged mode, devices or Docker socket (§9.5); `cpus` limits only as params that default to no limit (hosts without CPU CFS refuse a non-zero one); no dependency on Engine 25+ features such as healthcheck `start_interval`.
2. **App-native data commands in its own image:** `backup` (into a stage directory or to stdout; consistent with writers stopped, or online when declared), `restore` (into an empty target only), `verify` (read-only; recommended), `migrate` (idempotent, or observable through a schema read) and a schema read (a read task printing JSON, or a readiness probe that reports expected and actual schema). The backup command must also be runnable by hand against a deployment made outside Ingat, so that deployment can be adopted ([`LIFECYCLE.md`](LIFECYCLE.md) §4.16).
3. **An exit-code contract** for every command, documented in the app: `0` success, and distinct codes for "refused, nothing changed", "outcome unknown" (write commands) and "findings" (read checks). The manifest's `exit` maps encode it; an undeclared non-zero exit of a write task counts as `unknown`.
4. **Health and readiness probes:** a readiness check that passes only when the store is usable and the schema is current (ideally JSON with release and schema fields), and a TCP-level readiness check for each data store (a container's `healthy` is not enough: F16).
5. **Secrets as files** (Compose secrets or `*_FILE` variables), never baked into images or passed on argv; side-effect switches (real mail, payments, webhooks) as owner-gated keys; outbound side effects declared with holds and an app-level pause after restore.
6. **Images:** CI publishes images (owner decision OD-11, ADR-0026) for the architecture of every host the app runs on (`linux/amd64`, and `linux/arm64` for arm64 hosts) to GHCR by commit with the OCI `version` and `revision` labels; runtime bases pass a canary on the host's kernel and CPU (for example a DSM 4.4 kernel, as spike S15, and the x86-64 level the image requires: §11.4).
7. **`ingat.toml`** at the repository root, generic (no host values), with `ingat validate` in app CI on a pinned tool digest from the first commit and `ingat conformance` nightly once M3 exists.
8. **Host values outside the repository:** ports, subnets, URLs, hostnames and secrets only in `instance.toml` and secret files on the host and in the owner's offline encrypted copy (owner decision OD-9).

**When the deferred `cold` strategy is triggered** ([`ROADMAP.md`](ROADMAP.md) §4): an app that cannot provide item 2 (for example a third-party image without backup and restore commands), an app to adopt whose backup command the owner cannot run against its foreign deployment ([`LIFECYCLE.md`](LIFECYCLE.md) §4.16), or an incident in which app hooks could not preserve data. `cold` then stops the project, copies the declared stores with a helper container and restores only with the same data-image ID; it is designed by ADR when one of these occurs.

### 11.4 Minimum host requirements

A host must meet these before it can be certified. Meeting them does not make a host supported: every platform build still needs its own host certification (§3.6, §10.4), and support claims name only tested combinations.

- **Engine and Compose.** A local Linux Docker Engine 24.0 or later (API 1.43 or later) with Compose v2 or later as the `docker compose` plugin, reachable through the local socket `/var/run/docker.sock` as root (Ingat itself runs the Compose bundled in its image, never the host's: §3.2). On a Linux host, docker-ce from Docker's repository pinned by version, or a distribution package on an Engine line that CI tests (§3.4). Rootless and remote daemons and the other combinations of §11.1 are unsupported.
- **Access and scheduling.** SSH (or a local console) with an account that can `sudo` to root (Docker needs root); a scheduler that runs root jobs without a terminal and reports failures: systemd timers, cron, or the platform's scheduler such as DSM Task Scheduler ([`LIFECYCLE.md`](LIFECYCLE.md) §7).
- **CPU.** `x86_64` (amd64) or `aarch64` (arm64); arm64 only for the Engine lines its CI lane passes (§10.1). Ingat's own image targets each architecture's baseline (x86-64; Debian's arm64 baseline, ARMv8-A). An app image must exist for the host's architecture and may require a higher CPU level (for example images based on RHEL or UBI 9 need x86-64-v2), which the per-image canary checks (§11.3 item 6).
- **RAM.** Ingat itself needs little (Unverified: not measured yet; M0 records it). The apps dictate the rest, and a drill starts a second copy of an app's data services, so plan RAM for the live instances plus one drill copy. Recommendations (unmeasured): at least 4 GB for one PostgreSQL-backed app; 8 GB or more for several stateful apps with weekly drills.
- **Disk.** Room for the retained bundles, one extra data generation during a restore, and the images ([`LIFECYCLE.md`](LIFECYCLE.md) §5.8 checks the space per operation).
- **Platform note: Synology.** DSM 7.4 or later with Container Manager 24.0.2 or later, with its `docker compose` plugin present; DSM 7.1 and earlier with the legacy Docker package are unsupported (§11.1). Install values and traits: §3.4 and §11.2.

## 12. Risks

| ID | Risk | Mitigation |
|---|---|---|
| R1 | DSM profile: container-runtime behaviour (same-path binds, detached survival, TTY, flock across containers on an ext4 volume, the `local` logging override, `cpus: "0"`, routes on internal networks, `--rm` removal, the apps' images on a DSM 4.4 kernel) is **Unverified**; the missing CPU CFS quota is a confirmed fact of DSM 7.4.1 with Container Manager 24.0.2-1706 | M0 spike S1-S15 on the first host (a real DSM host) and in CI before feature code; fallback runtime: the same package run on the host with a pinned python-build-standalone plus static binaries under `INGAT_ROOT/runtime/<version>/` |
| R2 | docker CLI 29 / Compose v5 against Engine 24.0.2 (API 1.43) is **Unverified** in CI and on the first host (local scratch-dind runs only) | Required `docker:24.0.2-dind` lane; no on-host build (owner decision OD-11, ADR-0026); fallback to an older pinned pair |
| R3 | `image: sha256:<id>` pins, `build: !reset`, external generation volumes in an override are **Unverified** on the bundled Compose | Spike S5; fallback: tag → ID verification before every Compose call |
| R4 | DSM profile: `/volume1/ingat` may not survive a DSM update or repair | Certification item after the first DSM update; fallback: a dedicated admin-only shared folder whose subdirectories Ingat chmods explicitly, checked for ACL markers |
| R5 | Bundles hold personal data (for example signed documents and credential hashes) | `INGAT_BACKUPS` written only by root and certified so (on DSM a share read-only for administrators); client-side encryption of the off-host copy (restic or borg on Linux, Hyper Backup on DSM); doctor reports the ACL marker where the platform has ACLs |
| R6 | A drill or restore of the PostgreSQL consumer runs a second PostgreSQL; on-host builds of a Node frontend and a Python backend need RAM and time beside the live instances (RAM planning: §11.4) | `[drill] min_free_memory` refusal; drills off-hours and apart; builds in CI (owner decision OD-11, ADR-0026) |
| R7 | Always freezing on a writer image change costs minutes of downtime per release | Owner decision OD-4; the PostgreSQL consumer's web service keeps serving the app shell while the backend is stopped |
| R8 | A vendor container GUI's project actions (on DSM, Container Manager: "Clean" removes a project's containers, networks, volumes and images and "Delete" its data) or manual `docker compose` create drift | `status`/`doctor` report image-ID and config-hash drift, foreign objects and `changed-outside` (from M1); the operator guide forbids a vendor container GUI's project actions (Container Manager's on DSM) on Ingat projects; recovery from Ingat bundles (§11.2). Whether Container Manager lists and can Clean an Ingat-created project, and whether Clean removes external volumes, is Unverified; the rule applies either way |
| R9 | An Engine upgrade to a line without a CI lane (on a Linux host) blocks gate tier 2 until a tool release adds the lane; any change of the Engine build, kernel, OS release or storage driver (on Linux every kernel update, after its reboot) needs a `selftest --host` before gate tier 2, scheduled drills included, runs again | Pin the Engine package (docker-ce with `apt-mark hold` or the distribution's equivalent); move to a new line only with a tool release that tests it; run `ingat selftest --host` after each reboot into a new kernel; `uncertified` attention mails the owner |
| R10 | Scope creep (the earlier in-house deployment controller grew tenfold without a host run) | A walking skeleton that runs a real consumer (the SQLite consumer's `lite-test` instance) on the first host in M1 within its budget (about 3k lines, re-planned to about 6.6k with a stop line at about 10k: [ADR-0028](adr/0028-m1-replan-runtime-size.md)), module budget, consumer-justified features, the 1.5× stop rule ([`ROADMAP.md`](ROADMAP.md) §3) |
| R11 | DSM profile: the runc 1.1.7 of Container Manager 24.0.2-1706 is exposed to CVE-2024-21626 | Recorded by host certification; trusted images pinned by ID and digest; loopback-only ports behind the host's reverse proxy; LAN-only exposure of the host recommended; re-certify on a Container Manager build with a fixed runc (§11.2) |
| R12 | DSM profile: Node.js 24 (the SQLite consumer's runtime, the PostgreSQL consumer's web build stage) lists kernel 4.18 as its Tier-1 minimum; many DSM 7.x platforms run a 4.4.x kernel | Spike S15 before either app is declared supported, with its fallback ([`ROADMAP.md`](ROADMAP.md) M0) |
| R13 | DSM profile: DSM 7.4 reaches end of maintenance about June 2028 with no extended life | Re-certify on the next DSM line before then; the version gate refuses gate tier 2 on an uncertified build (§3.6) |
| R14 | DSM profile: on ext4 volumes Container Manager uses aufs, which was removed upstream in Engine 24.0 and survives only in Synology's build; a Container Manager build that switches the storage driver hides existing images and containers (volumes and bind generations survive) | `host check` compares the storage driver with `host.json` and treats a change as a new build needing re-certification; recovery is `prepare` (a re-pull of the recorded digests restores the images: ADR-0026) then `deploy` |
