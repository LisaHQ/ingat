# Ingat

**English** · [Tiếng Việt](README.vi.md)

[![CI](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

**Ingat installs, updates and backs up the apps you run with Docker Compose on your own server or NAS, and it never gambles with your data.**

Before any change that could touch your data, Ingat makes a backup and checks it. It never writes over your data. It proves that a backup really works by restoring it into a separate test copy of the app. And if your connection drops in the middle of an update, nothing is left half done: the work carries on, and you can always continue it or undo it.

*Ingat* means "remember, be aware, be careful" in Malay and Indonesian. In Tagalog the everyday goodbye *Ingat!* means "take care!". Say it close to "in-ngat".

> [!NOTE]
> **Early days.** Version 0.1.0 exists as a draft release and is not published yet. It handles simple apps today, passes all of its automatic tests on real Docker, and has passed its self-test on its first real machine, a Synology NAS. No real app runs under it yet, and restores come in the next milestone. Details: [Status](#status).

[What it does](#what-ingat-does) · [Why your data is safe](#why-your-data-is-safe) · [Get started](#get-started) · [Everyday use](#everyday-use) · [Status](#status) · [Where it runs](#where-it-runs) · [Learn more](#learn-more)

## What Ingat does

You keep a few apps running on one machine (a website, a shop, a small tool your team uses) with Docker Compose. Ingat is the careful helper for that machine. With one command each, it:

- **installs** an app from an exact version of its source code;
- **updates** it to a new version and moves its data forward safely;
- **backs it up**, every night or whenever you ask, and removes old backup copies by the keep rules you set;
- **checks** each backup copy, and **test-restores** it into a separate copy of the app to prove that it works;
- **starts, stops and restarts** the app, and runs the maintenance tasks the app provides;
- tells you in plain words what needs your attention, and which command to run next.

Planned for later milestones: restores (M2), going back to an older version and removing an app cleanly (M3), moving to a new machine and taking over an app that was installed without Ingat (M4).

Ingat works on one machine at a time, from the command line, usually over SSH. It is not a cluster manager, a hosting panel or a cloud service, and it does not copy your backups to another place: your own backup tool does that (restic, borg, rsync, or Hyper Backup on a Synology NAS).

## Who it is for

- **People who run their own apps** on a NAS, a VPS or a home server, and want the hard and risky parts done for them, safely.
- **App developers** who want their app to be easy and safe to install and update. They add one file, `ingat.toml`, to the app's repository ([how](docs/app-developers/MANIFEST_SPEC.md)).
- **AI assistants that run servers for their owner.** Ingat is built as a safety harness for them: they may look around and take backups freely, but a change needs the owner's approval, and anything that can lose data can only be approved by a person typing at a real terminal. This holds for assistants that follow the rule; their own tool settings enforce it. The way for an owner to hand an approved plan to an assistant comes in M2.

## Why your data is safe

| Promise | What it means for you |
|---|---|
| **A backup before every risky change** | Before an update that touches your data, Ingat stops the parts of the app that change your data, makes a backup copy, seals it with checksums and checks it. Only then does it change anything. If the backup fails, nothing is replaced. |
| **Nothing is written over** | A restore fills a new, separate data area and only then switches the app over to it. Your previous data stays as it was. (Restores come in M2; the rule is already part of the design.) |
| **Backups are proven, not hoped for** | A backup copy counts as "test-restored" only after Ingat restored that exact copy into a separate test copy of the app, which cannot reach your live data, and the app's own checks passed. |
| **Interruptions are safe** | Changes run in a helper on the machine, not in your SSH window, so a dropped connection stops nothing. The one exception is a task that talks to you in the terminal (for example a setup step of a first install): it runs from your window, so if the connection drops, run your next command and follow what it says ([operator guide §8](docs/guide/operator-guide.md#8-when-something-goes-wrong)). Ingat writes down each step before it takes it, so an interrupted job can always be continued or undone. |
| **It deletes only its own things** | Ingat removes only what it created, can prove it owns, and listed in a plan first. It never runs `docker system prune` or `docker compose down -v`, and it never touches containers, volumes or networks it did not create. |
| **Passwords stay private** | Passwords and keys live only in files that only root can read. Ingat never puts them on a command line, in its records, in backups, in logs or in error messages. |
| **No "force" switch** | There is no `--force` and no `--yes`. When Ingat says no, nothing has changed, and the message names the safe command to run instead. |
| **Only on tested machines** | Commands that change anything run only on Docker versions this release was tested with, and only after Ingat has tested your machine (`ingat selftest --host`). |

The exact rules are the 17 safety floors in [`docs/design/LIFECYCLE.md`](docs/design/LIFECYCLE.md#1-safety-floors). They are written in code, and no setting turns them off.

## Get started

### What you need

- A machine with **Linux, Docker Engine 24.0 or later and Docker Compose v2**: a server, a VM or VPS, a small board, or a NAS that runs Docker. Processor: `x86_64`, or `arm64` with Docker 29.9.
- **A tested Docker version, to make changes.** Ingat changes things only on a Docker version this release was tested with: today 24.0 or 29.9 on `x86_64`, 29.9 on `arm64`. On another version from 24.0 up it can only look and take backups that do not stop the app. Keep Docker from updating by itself ([operator guide §1](docs/guide/operator-guide.md#1-before-you-start)).
- **Root access**, usually over SSH (`sudo -i`).
- A **scheduler** for the nightly jobs (systemd timers, cron, or Task Scheduler on a Synology NAS) that emails you when a job fails.
- A tool that **copies your backups to another place** (restic, borg, rsync, or Hyper Backup on a Synology NAS).
- **Memory:** Ingat itself needs little. Plan for your apps, plus one extra copy of an app's data services while a test restore runs. Suggested, not yet measured: at least 4 GB for one app with PostgreSQL, 8 GB or more for several apps with weekly test restores.

Full list: [minimum host requirements](docs/design/ARCHITECTURE.md#114-minimum-host-requirements).

> [!IMPORTANT]
> **The first release is not public yet.** Version 0.1.0 is a draft on GitHub. Once it is published, download `install.sh`, `facts.sh` and `SHA256SUMS` from its [release page](https://github.com/LisaHQ/ingat/releases) into one folder (for example with `curl -fLO https://github.com/LisaHQ/ingat/releases/download/v0.1.0/install.sh`, and the same for `facts.sh` and `SHA256SUMS`) and follow the steps below.

### Step 1: install Ingat

**On a Linux server or VPS**, as root:

```sh
sudo -i
cd /path/to/downloads   # the folder where you saved the release files
sh install.sh --version 0.1.0 --link /usr/local/bin/ingat
```

Ingat keeps its own files in `/srv/ingat` and the backups in `/srv/ingat-backups`. `--link` lets you type `ingat` instead of `/srv/ingat/bin/ingat`.

**On a Synology NAS** (DSM 7.4 or later with Container Manager 24.0.2 or later):

1. In DSM Control Panel, create the shared folder `ingat-backups`: read-only for administrators, no access for anyone else. Add it to a Hyper Backup task, with encryption, that copies it off the NAS every night after the backups.
2. Turn on SSH, log in, and run:

   ```sh
   sudo -i
   cd /path/to/downloads   # the folder where you saved the release files
   sh install.sh --version 0.1.0 --root /volume1/ingat --backups /volume1/ingat-backups
   ```

   Always give these two folders on a NAS. The default `/srv` would sit on the small system partition, which a DSM update can reset. Below, `ingat` stands for `/volume1/ingat/bin/ingat`.

No internet on the machine? Add `--from-tar ingat-0.1.0-amd64.tar` (or `ingat-0.1.0-arm64.tar` on an `aarch64` machine) to load Ingat from that release file instead of downloading the image. Download the file from the same release page on another computer and copy it into the same folder.

<details>
<summary>All install options</summary>

| Option | Meaning |
|---|---|
| `--version X.Y.Z` | Required. The version to install. The image is pulled as `ghcr.io/lisahq/ingat@sha256:…`, the exact digest that `SHA256SUMS` lists for that version |
| `--root DIR`, `--backups DIR` | Full paths of Ingat's own folder (`INGAT_ROOT`) and of the backups folder (`INGAT_BACKUPS`); letters, digits and `/ . _ -` only |
| `--from-tar FILE` | Load this release file with `docker load` instead of pulling (its SHA-256 must be listed in `SHA256SUMS`) |
| `--link PATH` | Also create a shortcut to the `ingat` command (scheduled jobs always use the full path) |

The installer creates a missing `INGAT_ROOT` as `root:root 0700` (only root may open it) and the labelled volume `ingat-probe`, runs a self-check of the new image, and then writes the `ingat` command to `<root>/bin/ingat`. Run again with the same `--root` on a machine that already has Ingat, it is the upgrade: it refuses while any operation is unfinished (exit 2), runs `selftest --host` with the new version, keeps the current version if that fails (exit 3), and otherwise keeps the old command as `bin/ingat.prev`. Details: [`docs/design/ARCHITECTURE.md`](docs/design/ARCHITECTURE.md#34-install) §3.4-§3.5.

</details>

### Step 2: let Ingat check your machine

Do this once:

```sh
ingat host init           # links Ingat to this Docker; type the name the hostname command prints, to confirm
sh facts.sh > facts.json  # writes down facts about this machine (it changes nothing); keep the file
ingat selftest --host     # tests Ingat here with throwaway apps; takes a few minutes
ingat status              # "gate tier 2 (everything)" means Ingat may now make changes here
```

After every update of the system, the kernel or Docker, run `ingat selftest --host` again.

On a NAS, give `facts.sh` the same folders: `sh facts.sh --root /volume1/ingat --backups /volume1/ingat-backups > facts.json`.

### Step 3: add your first app

Your app needs an `ingat.toml` in its repository and images built by its CI ([checklist for app developers](docs/design/ARCHITECTURE.md#113-generality-rule)). Then:

1. **Describe this installed copy of the app** (an *instance*) in a small file in Ingat's inbox, for example `/srv/ingat/inbox/lite-test.toml` (on a NAS: `/volume1/ingat/inbox/lite-test.toml`): its name, where the source is, its port and addresses, how many backups to keep. [Example](docs/guide/operator-guide.md#3-add-your-app).
2. **Register it:** `ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0`, then type `lite-test` to confirm.
3. **Install it:** `ingat deploy lite-test v1.2.0`. Ingat shows its plan step by step; type `lite-test` to approve. If the app has setup steps, the install stops part-way (`paused`, exit 4) and says what to do; do that, then run `ingat resume lite-test`.
4. **Look at it:** `ingat status lite-test`.
5. **Schedule** the nightly backup and the weekly test restore ([how](docs/guide/operator-guide.md#7-nightly-and-weekly-jobs)).

Ingat runs inside a container that can see only its own two folders. Put every file you hand to it (instance files, app checkouts, task inputs) in the inbox, `INGAT_ROOT/inbox/`.

The [operator guide](docs/guide/operator-guide.md) walks through all of this in more detail.

## Everyday use

`lite-test` is an example instance name.

| I want to… | Command |
|---|---|
| See how everything is doing | `ingat status` (or `ingat status lite-test` for one app) |
| Make a backup now | `ingat backup lite-test --reason "before the mail change"` |
| Check the newest backup | `ingat verify lite-test --latest` |
| Prove that it can be restored | `ingat verify lite-test --latest --restore-test` |
| Update to a new version | `ingat deploy lite-test v1.3.0` |
| Stop, start or restart the app | `ingat stop lite-test`, `ingat start lite-test`, `ingat restart lite-test` |
| Read the app's logs | `ingat logs lite-test app --since 1h` |
| Run a task the app provides | `ingat task lite-test <task>` |
| Remove old backups by my keep rules | `ingat prune lite-test --bundles`, then the same with `--apply` |
| Continue or undo an interrupted job | `ingat resume lite-test` or `ingat abandon lite-test` |
| Watch a running job again | `ingat attach lite-test` |
| Upgrade Ingat itself | Download the new release's `install.sh` and `SHA256SUMS`, then run `sh install.sh --version <new version>` with the same `--root` and `--backups` you installed with |

When there is something to do next, the last line, `next:`, names the command to run. Reading, backups and checks never ask for approval. A change asks you to type the instance name (for example `lite-test`); a scheduled job can never approve a change, so it refuses instead. Add `--json` to any command for one block of machine-readable output.

<details>
<summary>All commands in version 0.1.0 (milestone M1)</summary>

Run as root. Approval classes: A reads only, B only adds things (backups, checks) or removes what your keep rules allow, C changes something and asks you to type the instance name (for `host init`, the name that the `hostname` command prints) on a terminal ([`docs/design/LIFECYCLE.md`](docs/design/LIFECYCLE.md#2-approval-classes-and-commands) §2). Exit codes are in [§6](docs/design/LIFECYCLE.md#6-exit-codes-every-command). The paths that `init --config` and `validate` take must be full paths inside one of Ingat's two folders.

| Command | What it does |
|---|---|
| `version` | Versions of the tool, the `ingat` command and the image |
| `host init`, `host check` | Link Ingat's folder to this Docker engine and record its facts (class C); record the facts and risks as a host check |
| `init <i> --config <file> --ref <ref>` | Register an instance from its `instance.toml` (class C) |
| `validate <repo-dir> [--instance <file>]` | Check an app repository, and optionally an instance file, without changing anything |
| `prepare <i> <ref>` | Fetch that version, download its images and pin them (class B) |
| `deploy <i> <ref>` | First install, update that changes data, update that changes only settings, or the way forward after a stopped update (class C); prepares first when needed |
| `start\|stop\|restart <i> [<service>…]` | Start, stop or restart the recorded deployment (class C) |
| `task <i> <task> [--arg NAME=VALUE]… [--input NAME=FILE]…` | Run a task the app declares (class B when it only reads, else C); `--input` names a file in `INGAT_ROOT/inbox/` |
| `backup <i> [--class <class>] [--reason TEXT] [--prune]` | Make a sealed, checked backup copy (class B; `--class` defaults to `manual`) |
| `verify <i> <bundle>\|--latest [--restore-test]` | Check a backup copy again; `--restore-test` also test-restores it (class B) |
| `prune <i> --bundles [--apply]` | Remove old backup copies by the keep rules: a dry run, or the removal with `--apply` (class B) |
| `resume <i>`, `abandon <i>` | Continue the unfinished operation, or undo what can be undone and close it (class C) |
| `attach <i>`, `cancel <i>` | Follow the running operation again; ask it to stop at its next safe point |
| `status [<i>]`, `doctor <i>`, `list`, `ps <i>`, `logs <i> <service> [--since T]`, `history <i>`, `bundles <i>` | Look without changing anything (`status` ends with exit 5 when something needs your attention) |
| `scheduled backup <i>`, `scheduled verify <i> <bundle>\|--latest [--restore-test]`, `scheduled task <i> <task> …`, `scheduled status` | Jobs for the machine's scheduler: classes A and B only, one line when they succeed (`scheduled status` prints only what changed) |
| `selftest [--host\|--offline]` | Run throwaway apps from start to end; `--host` also certifies this machine's system and Docker build; `--offline` checks the image without Docker |

</details>

## Status

As of 2026-10-22.

**Works today** (version 0.1.0, milestone M1), for apps built from a git repository that keep their data in plain folders, or keep no data:

- installing Ingat, checking the machine (`host init`, `host check`, `selftest`) and upgrading Ingat safely;
- registering an app (`init`), checking an app repository (`validate`), downloading and pinning its images (`prepare`);
- the first install, with pauses for the app's setup steps; updates that change data (backup first); updates that change only settings; and the safe way forward when an update stopped half-way;
- start, stop, restart and the app's own tasks;
- backups (by hand and nightly), checks, test restores, and removal of old backups by your keep rules;
- `status`, `doctor`, `list`, `ps`, `logs`, `history`, `bundles`;
- operations that keep going when SSH drops, with `attach`, `cancel`, `resume` and `abandon`.

**Tested:**

- The automatic tests run on real Docker for every push to `main` and every night, and they pass on all three lanes: Docker Engine 24.0 and 29.9 on `x86_64`, and 29.9 on `arm64` ([CI runs](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml)).
- The first real machine, a Synology NAS on DSM 7.4.1 with Container Manager 24.0.2-1706 (`x86_64`), passed `ingat selftest --host` with version 0.1.0 (22 checks). Its [certification](src/ingat/support/hosts/dsm-7.4.1-90080-0-containermanager-24.0.2-1706-4.4.302+-x86_64.json) is committed; the manual items of its checklist are still open.

**Not done yet:**

- Release v0.1.0 is a draft, not published. Its image `ghcr.io/lisahq/ingat:0.1.0` is public.
- No real app runs under Ingat yet. The first one, `lite-test` (the SQLite consumer) on that NAS, completes milestone M1; the M1 exit gate has not passed. M2 comes next.
- An upgrade from one real release to the next is not tested yet: until a second release exists, the test upgrades between two builds of the same version.
- Not in this version: restores; apps with Docker volumes or a separate database service; apps deployed from an image only; `exec` tasks; `secret set`; the plan hand-over for AI assistants; commands that can lose data (class D); a few app manifest features (file streams, log snapshots, deploy pre- and post-checks, a task-based `[schema]`); and `doctor`'s comparison of the proxy address it sees with the configured one.

**Decided, not built yet:**

- **Data providers** ([ADR-0031](docs/design/adr/0031-data-providers.md)): an app lists its data sets (PostgreSQL, MySQL, MariaDB, SQLite, plain files), and Ingat's own pinned helper images back them up, check them and restore them, so an app needs no backup commands of its own. A public catalog of certified apps. The public contract that provider images follow, and the first images, come alongside M2, the rest right after the M2 exit gate.
- **`ingat ui`** ([ADR-0032](docs/design/adr/0032-local-session-bound-web-view.md)): a read-only web page for your session, open only on the machine itself, with plain explanations and a helper that writes the command for you. Its first version has no access to Docker. It comes after the M2 plan hand-over.
- **`ingat report` and `ingat support-bundle`** ([ADR-0033](docs/design/adr/0033-commercial-boundary-report-and-hosted-service.md)): one outbound status summary that you sign up for, and a package of facts to share when you ask for help. With M2 or M3.

**Free, and it stays free.** Ingat is open source under the Apache License 2.0. Nothing that keeps or recovers your data will ever be paid, limited or tied to a plan. A hosted status page may become a paid service later ([ADR-0033](docs/design/adr/0033-commercial-boundary-report-and-hosted-service.md)).

### Roadmap at a glance

| Milestone | What it brings | State |
|---|---|---|
| M0 Decisions and machine facts | Name and namespace, facts about the first machine, runtime checks, where app images are built | In progress |
| M1 First real app | `lite-test` (the SQLite consumer) on the first machine, a Synology NAS; CI covers plain Linux | In progress: code done, exit gate open |
| M2 Restores and the PostgreSQL consumer | Restores into a new data area for both apps; `pg-staging` on the first machine; plan hand-over to AI assistants; the `ingat.toml` format frozen | Next |
| M3 Ready for production | Going back to an older version, removing an app, cleaning up, monitoring, helpers for systemd, cron and DSM schedules; `pg-prod` (when owner decision OD-5 allows) | Planned |
| M4 Disaster recovery and taking over apps | Restore on another machine, import, taking over an app installed without Ingat; certification of a plain Linux server (once such a server is available) | Planned |
| M5 Ingat upgrades itself | Self-upgrade and record migration commands | When needed |

Details, sizes and exit gates: [`docs/design/ROADMAP.md`](docs/design/ROADMAP.md).

## Where it runs

Ingat handles the differences between machines by checking what each machine can do, never by its brand, vendor or model.

| | Machines | What they need |
|---|---|---|
| **Supported** | Linux on any distribution (server, VM, VPS or small board) with upstream Docker Engine on a line the CI tests: today 24.0 and 29.9 on `x86_64`, 29.9 on `arm64` | `ingat selftest --host` on the machine, again after every kernel, system or Docker update |
| **Supported, per certified build** | Appliances with their vendor's own Docker build. First: Synology DSM 7.4 or later with Container Manager 24.0.2 or later. Certified so far: DSM 7.4.1 build 90080 with Container Manager 24.0.2-1706 on `x86_64` | A committed certification for each build line, plus `ingat selftest --host` after every update |
| **Not supported** | Rootless Docker; Docker Desktop on Windows or macOS for real use (development only); Podman; Kubernetes or Swarm; several machines; Docker Engine older than 24.0, which rules out Synology DSM 7.1 and older with the old Docker package | No plans to add them in v1 |

Until a machine's system and Docker build is certified, Ingat still shows you everything and keeps making the backups that do not stop the app, but it refuses every change. More: [`docs/design/ARCHITECTURE.md`](docs/design/ARCHITECTURE.md#11-hosts-and-support-matrix) §11.

<details>
<summary>Support tiers and platform traits, in the words of the spec</summary>

Summary of [`docs/design/ARCHITECTURE.md`](docs/design/ARCHITECTURE.md) §11.1-§11.2:

- **Support tier 1:** Linux hosts running upstream Docker Engine (docker-ce or a distribution package) on an Engine line CI tests, on `x86_64`, or on `arm64` for the lines its arm64 lane passes (29.x only). The CI lanes cover it from M1; mutating commands (gate tier 2) need a local `ingat selftest --host` certification of the host's platform build. The first committed generic Linux certification is Planned for M4 slice 12, once such a host is available.
- **Support tier 2:** vendor-built engines on appliances, Synology DSM 7.4 or later with Container Manager 24.0.2 or later (Synology's build of Engine 24.0.2, API 1.43) first. Each platform build line needs a committed certification from the full checklist, and every update a local `ingat selftest --host`, while nightly online backups continue and scheduled drills refuse until then. DSM 7.4 reaches end of maintenance about June 2028, so a move to the next DSM line is a planned re-certification.
- **Traits:** Ingat refuses a non-zero `cpus` limit at plan time on a host without CPU CFS quota, logs through the `local` driver whatever the daemon default (terminal tasks and the CLI through `none`), records an old runc (CVE-2024-21626) or missing seccomp as a host risk, depends on no particular storage driver or cgroup version, and rests recovery on sealed bundles plus an off-host encrypted copy made with the platform's tools, never on snapshots. Upstream dind cannot reproduce a vendor Engine, so only host certification covers one.

</details>

## How it works, in short

- Ingat is one pinned container image (`linux/amd64` and `linux/arm64`) with Python, the Docker command line, Compose and git inside, started by a 20-line root-only script. A server, a VPS and a NAS run exactly the same bytes; the Python and Compose of the machine itself are never used.
- Every change runs in a separate helper container (`ingat-exec-<instance>`), so a dropped SSH session or a scheduled job can never stop a data update half-way. The command you typed only plans, asks for approval and follows along. The exceptions are tasks that talk to you in the terminal, which run from your own window, and three short commands that only change Ingat's own records (`host init`, `init`, `secret set`).
- Compose always runs on the app's own Compose files plus a file Ingat generates, which pins every service to the exact recorded image and adds labels that never change between deployments, so an update recreates only the services whose settings changed.
- Each app keeps the knowledge of its own data in its own images. Its `ingat.toml` lives in the app's repository, is read from the exact version being installed, and declares its tasks (backup, restore, check, data update) and what each exit code means.
- A database counts as ready only after the readiness check the app declares for it has passed, not merely because its container has started.
- Every operation keeps a step log: each step is written down before it runs, and checked before it is retried. Only one operation per app may be open at a time.

The full design: [`docs/design/ARCHITECTURE.md`](docs/design/ARCHITECTURE.md) and [`docs/design/LIFECYCLE.md`](docs/design/LIFECYCLE.md).

## Learn more

| If you are… | Read |
|---|---|
| Running Ingat on your machine | [Operator guide](docs/guide/operator-guide.md): install, check the machine, add an app, everyday tasks, scheduled jobs, what to do when something goes wrong; every key of your instance file is in [`MANIFEST_SPEC.md` §6](docs/app-developers/MANIFEST_SPEC.md#6-instance-config-schema-1) |
| Making your app work with Ingat | [`docs/app-developers/MANIFEST_SPEC.md`](docs/app-developers/MANIFEST_SPEC.md): the `ingat.toml` and `instance.toml` files, with complete examples; the [onboarding checklist](docs/design/ARCHITECTURE.md#113-generality-rule) |
| Curious how Ingat works inside | [`docs/design/ARCHITECTURE.md`](docs/design/ARCHITECTURE.md) (design, security, testing, supported machines) and [`docs/design/LIFECYCLE.md`](docs/design/LIFECYCLE.md) (safety floors, approvals, every operation step by step, exit codes) |
| Following the plan | [`docs/design/ROADMAP.md`](docs/design/ROADMAP.md): milestones, exit gates and what waits for a trigger |
| Asking why a choice was made | [`docs/design/adr/`](docs/design/adr/README.md): one decision record per choice |
| Contributing, or an AI development agent | [`CLAUDE.md`](CLAUDE.md) first: the rules for every change |

The docs are sorted by reader: [`docs/guide/`](docs/guide/) for people who run Ingat, [`docs/app-developers/`](docs/app-developers/) for app developers (it also defines the instance file that operators write), and [`docs/design/`](docs/design/) for the design, the plan and the decision records; app developers also need the [onboarding checklist](docs/design/ARCHITECTURE.md#113-generality-rule) there.

Every Markdown document except [`CLAUDE.md`](CLAUDE.md) has a Vietnamese version beside it, named `<name>.vi.md`. The English version is the reference.

## Words used in Ingat

| Word | Meaning |
|---|---|
| **instance** | One installed copy of an app on your machine, with its own name (for example `lite-test`). The name is also its Docker Compose project name. |
| **app manifest** (`ingat.toml`) | A file in the app's repository that tells Ingat how the app works: its services, its data, its tasks. It holds no values of your machine. |
| **instance file** (`instance.toml`) | Your settings for one instance: source, ports, addresses, keep rules. It stays on your machine. |
| **backup copy** (bundle) | A sealed backup of one instance's data, with a checksum for every file, kept in `INGAT_BACKUPS`. |
| **checked** (verified) | Ingat re-read every file of the backup copy, found it unchanged, and the app's own checks passed, if the app has any (without them, only the files are checked). |
| **test restore** (drill), **test-restored** (restore-tested) | Ingat restored the backup copy into a separate test copy of the app that cannot reach your live data, checked it, then removed the test copy. |
| **writers** | The parts of the app that change your data. |
| **data area** (data generation) | One complete set of an app's data. A restore fills a new one; the old one is kept. |
| **operation** | One run of a command that changes things, written down step by step so it can be continued or undone. |
| **forward point** | The step of an update after which Ingat can no longer simply undo it (usually the app's data update). |
| **on hold** (frozen) | An update stopped after it had started changing data, so the writers are kept stopped on purpose until you take the way forward. |
| **approval classes** | A: reads only. B: only adds things (backups, checks) or removes what your keep rules allow; runs unattended. C: changes something; you type the instance name. D: can lose data; you type a phrase plus a random code on a real terminal (from M2). |
| **host certification** | The record that `ingat selftest --host` passed on this exact build of your system and Docker. |

## Conventions used in every document

- **Status tags:** **Decided** (part of the design), **Planned Mx** (decided, built in milestone x), **Open OD-n** (needs an owner decision), **Unverified** (a platform fact that the M0 spike or a later spike must confirm).
- **One verdict vocabulary** for gates, CI and reports: `PASS`, `FAIL`, `BLOCKED`.
- **Owner decisions** are cited as "owner decision OD-n". OD-1, OD-2, OD-3 and OD-11 are decided; the others are open and recorded in the owner's private notes, which are not part of this repository.
- **Generic consumers.** Two real apps drive the design. They are named here only by generic aliases:
  - *the PostgreSQL consumer*: a multi-service web app (PostgreSQL, a backend and a web service) with an explicit migrate step, role grants after a restore and an invariant-check command; mirrored by the fixture `fx-pg`;
  - *the SQLite consumer*: a single-container app with SQLite in a bind-mounted data directory, an online app-native backup, an outbound mail queue and a migrate at start; mirrored by the fixture `fx-lite`;
  - `fx-web`: a stateless fixture.

  Example instance names: `pg-staging`, `pg-prod`, `lite-test`, `site`.
- **The predecessor** is "an earlier in-house deployment controller". Ingat is rebuilt from scratch and has **no compatibility** with it: no shared labels, roots, records, bundles, volumes or images, and it reads none of its formats. Lessons from it appear as short generic reasons, never as citations. Taking over a deployment made outside Ingat is a product feature (adoption, M4).

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

In code these names live only in `src/ingat/brand.py` and the wrapper template ([ADR-0003](docs/design/adr/0003-name-namespaces-and-brand-module.md)); the docs use them literally.

## Contributing and AI agents

Read [`CLAUDE.md`](CLAUDE.md) before changing anything. It is the instruction file for AI development agents and applies to human contributors too: the public content rule (generic content only, no consumer or host values), the layers, the safety floors, testing and the commit-description format. Development agents never run Ingat, `docker` or `install.sh` against a real machine; they use CI and throwaway Docker daemons only.

## License

Ingat is licensed under the [Apache License 2.0](LICENSE).
