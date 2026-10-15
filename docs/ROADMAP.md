# Ingat roadmap

Status: **Decided** plan; no milestone has started. Durations assume one owner working with AI coding agents and are estimates, not commitments. Sizes are runtime lines (Python plus shell); tests are planned at roughly 1:1. Evidence for every exit gate is a CI run at a commit SHA or a committed host certification file, judged with `PASS`, `FAIL` or `BLOCKED` only.

Scope is committed through M4: the owner requires the full feature set (backup, verify, restore, schema and data migration on update, rollback, purge, disaster recovery with cross-host restore, and adoption of a deployment Ingat did not create) for every app deployed later (owner answers, 2026-10-14). Only M4's generic Linux host certification slice and M5 wait for a trigger.

**Consumers and hosts.** Two real consumers drive the milestones, named here by generic aliases: **the SQLite consumer** (a single-container app with SQLite in a bind-mounted data directory, an online app-native backup, an outbound mail queue and migrate at start), mirrored by the fixture `fx-lite`; and **the PostgreSQL consumer** (a multi-service web app with PostgreSQL, a backend and a web service, an explicit migrate step, role grants after restore and an invariant-check command), mirrored by the fixture `fx-pg`. `fx-web` is the stateless fixture. Example instances: `lite-test`, `pg-staging`, `pg-prod` and a stateless `site`. Changes in a consumer's own repository are consumer-side changes recorded in the owner's notes. Ingat targets any host with a local Linux Docker Engine and Compose v2 ([`ARCHITECTURE.md`](ARCHITECTURE.md) §11): from M1 the CI lanes on upstream Engine (support tier 1; `x86_64`, and `arm64` for the 29.x line once its lane passes) cover generic Linux hosts. **The first host**, the first real deployment, is a Synology NAS on DSM 7.4.1 with Container Manager 24.0.2, a support-tier-2 platform that needs its own host certification ([`ARCHITECTURE.md`](ARCHITECTURE.md) §11.1-§11.2).

## 1. Overview

| Milestone | Goal | Slices | Runtime lines | Estimate | Exit gate (summary) |
|---|---|---|---|---|---|
| M0 Decisions and host facts | Name confirmed, host facts folded in and certified by `facts.sh`, runtime spike decided, build location decided | 1 | ~300 (shell and spike code, mostly throwaway) | 1 week | Spike `PASS` or fallback chosen; OD-11 decided (OD-1, OD-2 and OD-3 decided 2026-10-14) |
| M1 Walking skeleton: **first real consumer** | The SQLite consumer's test instance on the first host, the first real deployment on a Synology NAS (a support-tier-2 platform), end to end through the detached executor; the CI support-tier-1 lanes cover generic Linux | 3 | ~3,000 | 3.5 weeks | Host evidence of the SQLite consumer's loop (install, scheduled backups, verify, drill, data-changing update); CI suites green on both engines |
| M2 PostgreSQL consumer staging and restores | The PostgreSQL consumer's staging instance on the first host (the Synology NAS); restores into a new generation for both consumers; plan hand-over to agents | 3 | ~2,200 | 2.5 weeks | Host evidence of the PostgreSQL consumer's loop and of a restore for both consumers; 7 nights of scheduled backups; manifest schema frozen |
| M3 PostgreSQL consumer production readiness | Rollback, purge, prune, monitoring, scheduling renderers (systemd, cron, DSM), conformance, docs; retire the PostgreSQL consumer's own shell release toolchain | 3 | ~1,150 | 2.5 weeks | Parity checklist `PASS`; purge rehearsed; the PostgreSQL consumer's production instance created (subject to owner decision OD-5) |
| M4 Disaster recovery, adoption and generic Linux certification | Import, cross-host restore, restore into a new instance, lineage, adoption by payload import; the generic Linux host certification (VPS or server) once such a host is available | 3 | ~1,000 | 2.5 weeks | A purged instance's final bundle and a bundle recovered from the off-host copy restored into new instances; a foreign deployment of the SQLite consumer adopted by payload import; first host → generic Linux host restore once one is available |
| M5 Tool evolution | Self-upgrade command, state migration framework, generated reference | 1 | ~500 | 1.5 weeks | Upgrade and rollback of the tool on the first host with an open-operation refusal |

MVP (M0-M2): about 5.5k lines (about 5.2k Python plus 0.3k shell), 7 slices. The first real consumer (`lite-test`) runs on the first host at the end of M1, about 4.5 weeks after the repository is created; `pg-staging` follows at the end of M2, about 7 weeks. Completion (M0-M5): about 8.2k lines, 14 slices, about 13.5 weeks. The systemd and cron renderers of `schedule render` moved from M4 slice 12 to M3 slice 8 because generic Linux hosts are first-class; that moves about 50 lines (M3 from ~1,100 to ~1,150, M4 from ~1,050 to ~1,000) and changes no total or duration.

## 2. Milestones

### M0 Decisions and host facts

**Content.**

- **Owner decisions.** OD-1, OD-2 and OD-3 were decided on 2026-10-14: the name Ingat (CLI `ingat`, label namespace `io.github.lisahq.ingat.`, image `ghcr.io/lisahq/ingat`), the GitHub organization LisaHQ, a public repository, a public image and generic content only. The name fixes every persistent identifier, so `github.com/LisaHQ/ingat` is created before any real resource. Decide owner decision OD-11 (where consumer images are built: (a) on the host in `prepare`, or (b) in each app's CI and pulled by digest) with the facts below.
- **Repository skeleton.** The generic design docs under `docs/` and `docs/adr/` (consumer notes stay in the owner's private notes: owner decision OD-3), [`CLAUDE.md`](../CLAUDE.md), CI skeleton with a `docker:24.0.2-dind` lane and a `docker:29.Y.Z-dind` lane (one exact 29.x tag, fixed in `image/versions.lock` in M0) on `ubuntu-24.04`, plus the arm64 lane on the GitHub-hosted arm64 runner `ubuntu-24.04-arm` (S13 confirms that it boots dind and is free for this public repository), `image/Dockerfile` with `versions.lock`, building one multi-arch image (`linux/amd64` and `linux/arm64`) from the first build, so M1 builds it multi-arch from its first commit.
- **Host facts.** Supplied by a read-only probe of the first host on 2026-10-14 (folded into [`ARCHITECTURE.md`](ARCHITECTURE.md) §11 as traits of the DSM and Container Manager release): DSM 7.4.1, Container Manager 24.0.2-1706, `docker version` and `docker info` (Engine 24.0.2, API 1.43, runc 1.1.7, no CPU CFS quota/period, no blkio throttle, logging driver `db`, cgroup v1, no seccomp), a DSM 4.4 kernel, x86_64. Ingat never deletes foreign resources: objects already on a host's daemon stay foreign. `facts.sh` (read-only host script) is still written in M0 and run by the owner: it produces the committed certification input in a stable format, with platform fields only ([`ARCHITECTURE.md`](ARCHITECTURE.md) §10.4), and records locally what the probe did not (free space on each root, available memory, ACL markers, the share permission). The spike also records Ingat's own peak memory (CLI and executor), which [`ARCHITECTURE.md`](ARCHITECTURE.md) §11.4 leaves unmeasured.
- Runtime spike on the first host and in CI, each item `PASS` or `FAIL` with logs:

| Spike | Question |
|---|---|
| S1 | Same-path binds, `env_file` and file secrets resolve correctly when Compose runs inside the tool container |
| S2 | A detached executor survives an SSH drop, a closed terminal and a killed client; its result reaches the follower; a root run from the host scheduler (no TTY; DSM Task Scheduler on the first host) gets the right exit code |
| S3 | `flock` on a bind-mounted file on an ext4 volume excludes across two containers |
| S4 | The bundled docker CLI (29.x, else 28.x) and Compose v5.x (else the last passing v2.x) work against Synology's Engine 24.0.2 (API 1.43): `config --format json --no-env-resolution`, `config --hash`, `up --wait`, `run --name --label -v`; the host's Compose v2.20.1 is never used. Only if OD-11 chose (a): buildx, and building both consumers' images with Bake on the first host, with build time and peak memory recorded while both consumer instances run |
| S5 | An override with `image: sha256:<id>`, `pull_policy: never`, `build: !reset null`, an external generation volume `name:`, `ports: !reset []`, `internal: true` networks and the `logging: {driver: local}` block starts exactly the pinned image and `docker logs` reads it on Synology's Engine; a terminal `compose run` with `logging: {driver: none}` still reaches the terminal; which inputs enter `config --hash` (labels, logging, `env_file` paths and contents) |
| S6 | Single-quoted values in `--env-file` and `env_file` are read literally |
| S7 | A `--network host` tool container reaches `127.0.0.1:<published port>` |
| S8 | `statvfs` on the `ingat-probe` volume equals `df` of DockerRootDir |
| S9 | `/volume1/ingat` created over SSH shows no `+` ACL marker and `synoacltool -get` is empty; root can write into `ingat-backups` while administrators have read-only access; persistence across a DSM update is recorded as pending until the next update |
| S10 | Prompts over SSH (`-t` only with a TTY) and Ctrl-C in the follower behave as designed |
| S11 | CPU and memory limits. **Confirmed by the first host's probe:** no CPU CFS quota/period support (the daemon refuses a create with a non-zero `cpus`); no blkio throttle (Docker discards blkio limits with a warning; no consumer sets them, so nothing is checked). Remaining check only: whether Compose `cpus: "0"` means no limit on the bundled Compose against this Engine, and that `--memory 256m` applies |
| S12 | A container on an `internal: true` network has no default IPv4 route on Engine 24.0.2, and the PostgreSQL consumer's web service, which refuses to start without a default IPv4 route unless a hold sets its trusted-proxy address (as `fx-pg`'s web service mirrors), starts in an isolated project with that hold |
| S13 | CI: `docker:24.0.2-dind` boots on `ubuntu-24.04` runners with working iptables, internal networks and port publishing; the pinned `docker:29.Y.Z-dind` does the same on the GitHub-hosted arm64 runner `ubuntu-24.04-arm`, and arm64 runners are free for this public repository |
| S14 | `compose run --rm` removal is daemon-side (`AutoRemove`) or client-side: what remains of the task container after the client is SIGKILLed mid-run |
| S15 | The consumers' runtime images run on a DSM 4.4 kernel (Node.js 24 lists kernel 4.18 as its Tier-1 minimum, "older may work"): the SQLite consumer's image (a Node.js 24 runtime with a native SQLite module) loads the module, migrates, starts, backs up and restores a fixture database; the PostgreSQL consumer's backend, web and PostgreSQL 16 images start and run their tasks; with on-host builds (OD-11 a) also its Node.js 24 build stage |

**Fallbacks** (decided now so the spike cannot stall the project):

- S1, S2 or S3 fail → host-run Python (pinned python-build-standalone plus static binaries under `INGAT_ROOT/runtime/<version>/`).
- S4 fails → the newest older CLI/Compose pair that passes.
- S5's ID pin fails → tag → ID verification before every Compose call. If labels, the logging block or file paths enter `config --hash` in an unexpected way, the override and file layout are adjusted so that only a real config change alters a service's hash ([`ARCHITECTURE.md`](ARCHITECTURE.md) §6.2). If the `local` driver is unavailable on Synology's Engine, the override uses `json-file` with the same rotation.
- S6 fails → restrict param values to `[A-Za-z0-9._:/@+-]` and secrets to files.
- S7 fails → `http` probes become `exec` probes inside a service container.
- S11 (no CPU CFS, confirmed) → the plan-time capability check refuses every model with a non-zero `cpus` limit ([`ARCHITECTURE.md`](ARCHITECTURE.md) §9.5), and the PostgreSQL consumer's instances set its `cpus` params to `"0"`. If S11 confirms that `cpus: "0"` means no limit, that consumer deploys unchanged and a consumer-side change defaulting its `cpus` limits to no limit is only recommended; otherwise that consumer-side change is required and removes the `cpus` keys.
- S12 shows a default route on internal networks → nothing changes; the hold is harmless.
- S13 fails → a runner image or dind iptables mode that boots Engine 24.0.2, recorded in an ADR; if none works, an ADR records it and defines the evidence that puts Engine 24.0 into `tested.json` (for example a self-hosted runner lane) before M1 slice 1 ends, because gate tier 2 needs a `tested.json` entry for the host's Engine line ([`ARCHITECTURE.md`](ARCHITECTURE.md) §3.6); until then gate tier 2 refuses on Engine 24.0 hosts, the first host included. If the arm64 runner cannot boot dind or is not free → the image stays multi-arch, `tested.json` carries no arm64 entry, so arm64 is not claimed, and an ADR records it.
- S14: either way task containers carry an attempt suffix and the orphan check records and removes exited ones ([`ARCHITECTURE.md`](ARCHITECTURE.md) §4.5); if `--rm` is daemon-side, a killed step's exit code is lost and the step's own `observe` rule decides.
- S15 fails for an app image → that app's repository moves the failing runtime to a base that passes S15 on kernel 4.4 (its own choice, recorded there) before the app's first Ingat deploy on the first host; a failing on-host build stage alone moves OD-11 to (b). If no runtime of the SQLite consumer passes before M1 slice 3, M1 is re-planned by ADR: the first real consumer on the first host becomes `pg-staging` (M2) and the SQLite consumer waits for a certified generic Linux host (M4 slice 12).
- **Build location (owner decision OD-11).** The decision rule chooses CI builds (b) when the host has less than 6 GB of RAM, is `aarch64`, or the S4 build of either consumer fails or exceeds the owner's time limit. For the first host the RAM condition is evaluated from its recorded facts (kept in the owner's notes), and the architecture condition does not fire (`x86_64`); the recommendation is CI builds regardless (OD-11 option b). With (b) the M0 ADR records the pulled-`build_services` addition, `prepare` pulls by digest from M1, each consumer's CI publishes its images (a consumer-side change), and the on-host build path (with buildx in the tool image and S4's build checks) moves to the deferred list (§4).

**Exit gate.** The first host's certification input from `facts.sh` committed (platform fields only); every spike item `PASS` or its fallback recorded in an ADR; OD-1 (decided 2026-10-14) and OD-11 decided; ADR files 0001-0025 ([`docs/adr/`](adr/README.md)) plus the M0 decision ADRs (OD-11 build source, spike fallbacks) committed.

### M1 Walking skeleton: first real consumer (3 slices)

The SQLite consumer is the simplest real consumer: one container, one bind store, app-native backup and restore. M1 runs it end to end on the first host, the first real deployment, on a Synology NAS (a support-tier-2 platform that needs its own host certification); from the same milestone the CI support-tier-1 lanes cover generic Linux hosts. Manifest schema 1 parses in full from v0.1, but M1 honours only the keys the SQLite consumer and the fixtures use; keys only the PostgreSQL consumer needs are implemented in M2 and may still change before the M2 freeze.

- **Slice 1 Foundations.** `brand.py`; runner (argv only, allowlisted env, timeouts, process groups, bounded redacted capture of text streams, byte-exact file streams); `store/fs.py`, locks, state layout and the record compatibility rule (ADR-0023); manifest and instance models with `validate`; templates; Compose policy with host capabilities; compose and docker adapters with the `EffectToken`; override generator (labels, image pins, logging block); git adapter; `install.sh` (generic default roots `/srv/ingat` and `/srv/ingat-backups`; the DSM profile passes its own) and the wrapper; `host init`, `host check` (the capability and platform-build facts of [`ARCHITECTURE.md`](ARCHITECTURE.md) §11.2), `init`, `doctor`, `status` (with `changed-outside`: missing or different containers, networks or generation volumes against the recorded deployment), `list`, `ps`, `logs`; the multi-arch image build, the arm64 lane and `tested.json` generation in CI (Engine line × architecture); the upgrade suite.
- **Slice 2 Executor and first install.** Plan framework and approval classes A-C with typed-name approval on a terminal; detached executor with follower, cancel, attach, vanished-executor detection; journal, resume, abandon, auto-abandon, orphan check over running and exited task containers; `prepare` (git source: pull of CI-built images by digest with a label check if OD-11 chose (b), otherwise an on-host build; image IDs); bind stores and generations; rendered env files with forbidden, tool-managed and owner-gated keys (a plan that changes an owner-gated key is refused until class D lands in M2); first install with `[[install]]` steps and a pause with allowed tasks; stateless deploy; `start`, `stop`, `restart`; `run`-mode tasks with mounts (stage, bundle, generation, input) and foreground terminal tasks; probes (`health`, `exec`, `http`) with stability windows; smoke and image identity check; `selftest` (through the executor).
- **Slice 3 Backups, drill and update; SQLite consumer onboarding.** `backup` (stage in the root, payload rule, seal, copy-then-rename into the backups root, catalog), `verify`, `bundles`, `prune --bundles`, `scheduled backup`, `scheduled status`; capacity checks per filesystem; gate tier 1; isolation override (internal networks, no ports, pool subnets, holds, isolated env file) and the drill (`verify --restore-test`) with evidence and closed teardown; data-changing update (freeze, pre-change bundle, migrate with exit maps, activation with `reopens_writes`, smoke) and config-only change; the plan-time schema gate for older refs; the SQLite consumer's manifest merged in its own repository (plus its CI image publishing if OD-11 chose CI builds); `lite-test` on the first host with its DSM reverse-proxy entry, Task Scheduler entries and the Hyper Backup task on `ingat-backups`.
- **CI suites green on both engines:** no-trace, crash matrix for M1 operations, session loss, upgrade, recreate scope, isolation on `fx-lite`, secret canary, version gate, policy table, static lints. `fx-web` is a CI fixture only. The arm64 lane runs the same suites; its verdict decides only whether arm64 enters `tested.json`, because the first deployment is amd64.
- **App CI:** `ingat validate` jobs in the SQLite consumer's repository (merged) and the PostgreSQL consumer's repository (a draft manifest; a validation failure there is a design input, not a blocker).

**Budget.** About 3,000 runtime lines; the 1.5× rule (§3) stops M1 at 4,500 lines for a re-plan ADR.

**Exit gate (host evidence on the first host, `lite-test`).**

1. `selftest --host` `PASS`; the first host certification committed.
2. First install: migrate once, start, the install pause with the consumer's bootstrap task run and journaled inside it, `resume`.
3. `scheduled backup` exit 0 on at least three consecutive nights, with retention applied; `scheduled status` mails only when the attention set changes.
4. `verify --latest` and one scheduled `restore-tested` drill.
5. One data-changing update (commit A → B) approved by typed name and run by the detached executor; an SSH drop during it leaves it completing.
6. CI suites `PASS` on both engines (`x86_64`); the arm64 lane's verdict recorded.

### M2 PostgreSQL consumer staging and restores (3 slices)

- **Slice 4 PostgreSQL consumer mechanics.** Volume stores, data services and store readiness (safety floor F16, [`LIFECYCLE.md`](LIFECYCLE.md) §1); `exec`-mode tasks; stdin/stdout file streaming with the `nonempty` check; generated file secrets and `secret set`; `prechecks` and `postchecks`; log snapshots; the class D challenge and `start --unfreeze`; `ingat plan` and `ingat apply` hand-over; image-source apps (`prepare --image`, `deploy --image`).
- **Slice 5 Restores.** `restore` into a new generation through `<i>--r<seq>` with switch, held state and `restore_notice`; generation-safety and isolation suites on `fx-pg` (including a service that refuses to start without a default route) and `fx-lite`.
- **Slice 6 PostgreSQL consumer onboarding.** The PostgreSQL consumer's manifest merged in its own repository, with its instances setting the `cpus` params to `"0"` (the consumer-side `cpus` change only if S11 requires it) and, if OD-11 chose CI builds, its CI image publishing; `pg-staging` on the first host with its deploy key, DSM reverse-proxy entry and Task Scheduler entries; the SQLite consumer's fixed-subnet Compose change (a consumer-side change) merged and `lite-test` redeployed on it (a data-changing deploy that also replaces the project network with the fixed-subnet one; writers are stopped first, so the network has no attached containers); the freeze time of a PostgreSQL consumer release measured (owner decision OD-4); operator quick guide (English) for both instances.

**Exit gate (host evidence on the first host).**

1. The PostgreSQL consumer's first install with its first-run setup pause.
2. Seven consecutive nights of `scheduled backup` exit 0 for both instances, with retention applied and failure mail tested once (a deliberately busy lock).
3. One `restore-tested` drill of `pg-staging`.
4. One data-changing update of the PostgreSQL consumer (`vX` → `vX+1`), including a deliberately failed update that ends `failed-frozen` and is recovered; the measured freeze time recorded.
5. One `restore` into a new generation for each instance; `lite-test` ends `held`, and the consumer's own task that resumes its outbound queue clears it.
6. An SSH drop during an update of the PostgreSQL consumer leaves the operation completing.
7. CI suites `PASS` on both engines. The manifest schema is frozen after this gate.

### M3 PostgreSQL consumer production readiness (3 slices)

**Start:** after the M2 exit gate; committed scope (rollback and purge belong to the required feature set). The PostgreSQL consumer's production go-live date, with owner decision OD-5, decides only when `pg-prod` is created.

- **Slice 7 Recovery commands.** `rollback` (code-only, restore-based with `[rollback] env`, `--accept-schema`), `restore --generation`, `resolve`, data-service image changes (`--data-image in-place|via-restore`), closed deletion executor generalised, `prune --generations`, `prune --images`, `purge`.
- **Slice 8 Monitoring and scheduling.** `check` (parity with the PostgreSQL consumer's existing monitor script: health and restarts, ready predicate, certificate expiry, disk thresholds on every root and the Docker root, backup and restore-test age, open operations, re-notify suppression; replaces `scheduled status`), `schedule render` for systemd timers (`--systemd`: oneshot units, timers with `Persistent=true` and an `OnFailure=` unit), cron as a fallback (`--cron`) and DSM Task Scheduler (`--dsm`), extended drift reporting. The systemd and cron renderers moved here from M4 slice 12 because generic Linux hosts are first-class (about 50 lines, §1).
- **Slice 9 Conformance and docs.** `conformance --repo . --from <ref>` (init → deploy → backup → verify → drill → update → rollback → restore → purge of a throwaway instance, all inside one command), nightly jobs in both consumers' repositories with a pinned tool digest (consumer-side changes); `{freeze_at}` and bundle-name conformance against the PostgreSQL consumer's real `migrate`; operator guide in English with a Vietnamese mirror under `docs/runbooks/vi/`, including the rule never to use a vendor container GUI's project actions (Container Manager's on DSM) on Ingat projects; generated command reference.

**Exit gate.** The parity checklist against the PostgreSQL consumer's existing shell release toolchain (kept in the owner's notes) all `PASS`; `purge` `PASS` on the first host (its final bundle sealed and catalogued; the restore-test gate exercised on a non-disposable instance); `pg-prod` created and first-installed (where owner decision OD-5 allows); that shell toolchain removed in a consumer-side commit.

### M4 Disaster recovery, adoption and generic Linux certification (3 slices)

**Start:** after the M3 exit gate; committed scope. Only slice 12 waits for a trigger: a generic Linux host (a VPS or a server) available for certification. Slices 10 and 11 share the import and restore-into-a-new-instance machinery, which is why adoption lives here.

- **Slice 10 Disaster recovery.** `import` (copy, verify, reject links and unlisted files, catalog as `imported`), restore into a new instance on any host (target config, ports, secrets and paths from the target; lineage inherited; a same-host bundle of a purged instance found by bundle id and re-hashed), `single_active` lineage check, `export-config` for owner custody, optional `include_images` (`docker save` archives in pre-change and final bundles), `host rebind`; the runbook for the loss of the host ([`ARCHITECTURE.md`](ARCHITECTURE.md) §11.1); CI: cross-host restore on two dind daemons in the nightly tier.
- **Slice 11 Adoption** ([`LIFECYCLE.md`](LIFECYCLE.md) §4.16; ADR-0024). Consumer need: the owner's requirement that apps deployed outside Ingat later can be taken over. `import --payload` (payload rule and bundle id, `consistency = "external"`, `origin`, the prepared candidate as the recorded deployment), restore of an imported bundle only after its drill, `adopted_from` in `record.json`; the adoption runbook in the operator guide (quiesce and export with the foreign project's own tooling, restart policies cleared, cut-over, rollback); the CI adoption suite on hand-made foreign `fx-pg` and `fx-lite` projects ([`ARCHITECTURE.md`](ARCHITECTURE.md) §10.3).
- **Slice 12 Generic Linux host certification (VPS or server)** (trigger: such a host is available). The Linux host runbook (docker-ce 29.x from Docker's repository pinned by version, or a distribution package on a tested Engine line; the backups root and its off-host copy with restic, borg or rsync; systemd timers from `schedule render --systemd`, M3), and the first committed generic Linux certification from the full checklist ([`ARCHITECTURE.md`](ARCHITECTURE.md) §10.4). The install path itself is generic from M1.

**Exit gate (slices 10-11, host evidence on the first host).** The final bundle of the instance purged in M3 restored into a new instance, then backed up and updated; a bundle recovered from the Hyper Backup destination into a directory under `INGAT_ROOT/inbox/`, `import`ed into a new instance initialised from the owner's offline encrypted copy of instance configs and secrets (owner decision OD-9), drilled, restored, then backed up and updated; a deployment of the SQLite consumer started with plain `docker compose` outside Ingat adopted by payload import into a new instance, then backed up, drilled and updated, with Ingat making no change to any foreign object (Docker events); the runbook's adoption rollback rehearsed once; CI suites `PASS`. **Slice 12 gate:** `lite-test` moved from the first host to the generic Linux host by bundle import and restore, then backed up and updated there; the generic Linux certification committed.

### M5 Tool evolution (slice 13)

**Trigger:** the first state-schema change, or the second tool upgrade done by hand. Upgrades with `install.sh` are tested from M1 by the upgrade suite ([`ARCHITECTURE.md`](ARCHITECTURE.md) §10.3); M5 adds the commands.

- `self-upgrade`, `self-rollback` (refuse while any operation is open; keep the previous image), `state migrate` (copy, then migrate; reads N and N-1), generated CLI reference.

**Exit gate.** On the first host: upgrade, refused upgrade during an open operation, rollback, all `PASS`.

## 3. Guardrails

- Every slice names the consumer need it serves; a feature without one is not built.
- A milestone that passes 1.5 × its line estimate stops for a re-plan ADR (an earlier in-house deployment controller grew about tenfold, from about 3k to about 29k lines, with no host run).
- No feature merges without its real-Docker tests.
- Manifest schema 1 is a draft until the M2 exit gate: M1 implements only what the SQLite consumer and the fixtures use, and keys only the PostgreSQL consumer needs may change when its onboarding shows a need. After the M2 gate the schema is frozen; a core change forced by any consumer, including a new app (the generality rule, [`ARCHITECTURE.md`](ARCHITECTURE.md) §11.3), is recorded as a generality failure in an ADR.
- Docs describe only what exists or is decided; each milestone updates [README](../README.md) status and `tested.json`.

## 4. Deferred work with explicit triggers

| Item | Trigger | Earliest milestone |
|---|---|---|
| `cold` data strategy | A consumer without app-native backup and restore commands, an app to adopt whose backup command the owner cannot run against its foreign deployment, or an incident where app hooks could not preserve data | after M3 |
| A `docker:24.0.2-dind` lane on arm64 (the arm64 lane runs 29.x only) | An arm64 host on Engine 24.0 needs gate tier 2 ([`ARCHITECTURE.md`](ARCHITECTURE.md) §10.1) | any |
| On-host image builds in `prepare` (with buildx in the tool image, S4's build checks and the build rules of [`ARCHITECTURE.md`](ARCHITECTURE.md) §9.6) | Only if OD-11 chose CI builds: an app without CI image publishing | any |
| GET-only Engine API client | Docker CLI JSON parsing proves fragile in CI | any |
| Tar bundles | A transport that cannot carry directories | after M4 |
| Rollout strategy for stateless services | A stateless site needs zero downtime | after M4 |
| Secret rotation commands | First planned rotation of a database role password of the PostgreSQL consumer | M3 or later |
| The SQLite consumer's read-only `verify`/`schema` integration (`verified` beyond hash; `observe = "schema"` for its `migrate`) | The SQLite consumer ships read-only verify and schema commands (a consumer-side change) | any |
| The SQLite consumer's outbound preview tasks as `read` (class B) | The SQLite consumer ships a preview mode for its outbound commands that writes nothing, with a distinct usage-error exit code (a consumer-side change) | any |
| The PostgreSQL consumer's accepted pre-existing findings (`baseline` plus a comparison task) | The PostgreSQL consumer ships a baseline mode for its invariant-check command (a consumer-side change; owner decision OD-7) | M3 |
| Restore in the current release (`--release current`, with a migrate step) | A consumer needs it; by ADR | after M3 |
| Non-loopback published ports (`public_ports`) | An app must publish on a non-loopback address; by ADR | any |
| Two-invocation preview flow with a bound output hash | A consumer whose confirm step cannot be a separate app command; by ADR | any |
| Never | Web UI, daemon, plugins, host hooks, auto-update, TLS, multi-host, ACL management (for example DSM ACLs) | — |
