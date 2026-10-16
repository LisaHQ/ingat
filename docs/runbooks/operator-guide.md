# Ingat operator guide (M1)

Status: describes the M1 command set as it exists in code ([`README.md`](../../README.md) "Commands (M1)"). Restores, class D approvals, `secret set` and the `plan`/`apply` hand-over to agents arrive in M2 ([`ROADMAP.md`](../ROADMAP.md)); this guide says so where it matters. The reasons behind every rule are in [`LIFECYCLE.md`](../LIFECYCLE.md) and [`ARCHITECTURE.md`](../ARCHITECTURE.md); this guide only says what to type and what you will see. A Vietnamese mirror is at [`vi/operator-guide.md`](vi/operator-guide.md).

Every command runs as root through the wrapper (`/srv/ingat/bin/ingat` under the default root; `/volume1/ingat/bin/ingat` in the DSM profile). Below, `ingat` stands for that path, and `lite-test` is an example instance of the fixture app `fx-lite`.

## 1. Before you start

- **Host:** a Linux Docker Engine 24.0 or later with the `docker compose` plugin, reachable as root through the local socket; SSH with `sudo -i`; a scheduler that mails failures (systemd timers, cron, or DSM Task Scheduler); a tool for the off-host copy of the backups (restic, borg, rsync, or Hyper Backup on DSM). Details: [`ARCHITECTURE.md`](../ARCHITECTURE.md) §11.4.
- **Two directories:** `INGAT_ROOT` holds the tool's state and the live data of bind stores (default `/srv/ingat`; it must be `root:root 0700`, on a local filesystem, never a network share). `INGAT_BACKUPS` holds the sealed backup bundles (default `/srv/ingat-backups`, written only by root, the source of your off-host copy). On DSM pass `--root /volume1/ingat --backups /volume1/ingat-backups` at install; never accept the `/srv` defaults there.
- **The tool sees only these two directories.** The CLI runs in a container that mounts `INGAT_ROOT` and `INGAT_BACKUPS` and nothing else of the host. Every path you give it (`init --config`, `validate <repo-dir>`, `validate --instance`, task `--input` files) must be an absolute path under one of them; `INGAT_ROOT/inbox/` is the place for such files and checkouts.
- **Your app:** needs an `ingat.toml` in its repository and CI-built images ([`MANIFEST_SPEC.md`](../MANIFEST_SPEC.md); the onboarding checklist in [`ARCHITECTURE.md`](../ARCHITECTURE.md) §11.3). `ingat validate <repo-dir>` checks a checkout offline (for example one under `INGAT_ROOT/inbox/`).
- **Tested Engine lines:** mutating commands run only on an Engine line the release tested (`tested.json` in the image) and only after a host certification. On another Engine line `ingat status` says `not a tested combination of this release`: read-only commands and online backups still work. Pin `docker-ce` on a Linux host (`apt-mark hold`) and move to a new line only with a tool release that tests it.

## 2. Install and certify the host (once)

As root, with the release's `install.sh` and `SHA256SUMS` in one directory:

```sh
sudo -i
sh install.sh --version 0.1.0          # default roots; add --root and --backups for the DSM profile
ingat host init                        # binds the root to this engine; type the host name to approve
sh facts.sh > facts.json               # read-only host facts; keep the file with your notes
ingat selftest --host                  # certifies this platform build: one summary line, then nothing until done (minutes)
ingat status                           # "gate tier 2" among the last lines means mutating commands may run
```

On the DSM profile pass the roots to `facts.sh` as well: `sh facts.sh --root /volume1/ingat --backups /volume1/ingat-backups > facts.json`.

What you will see: `install.sh` prints the offline selftest lines and `installed version …`; `host init` prints the engine, storage driver and kernel, then either `gate tier 2: this platform build is certified` or the reason it is not; `selftest --host` prints one `PASS` line per check and the path of the certification it wrote. Repeat `ingat selftest --host` after every OS, kernel or Engine update: until then `status` shows `uncertified` attention and scheduled drills refuse (exit 2) while nightly online backups continue.

Offline install: `sh install.sh --version 0.1.0 --from-tar ingat-0.1.0-amd64.tar` loads the release tarball instead of pulling.

## 3. Register an instance

1. Write the instance file into the inbox, for example `/srv/ingat/inbox/lite-test.toml` (schema and a full example: [`MANIFEST_SPEC.md`](../MANIFEST_SPEC.md) §6 and §12). The minimum for `fx-lite`:

   ```toml
   instance = 1
   name = "lite-test"
   app = "fx-lite"
   environment = "test"
   disposable = false

   [source]
   repo = "ssh://git@github.com/<owner>/<app>.git"
   key = "fx-lite"                      # /srv/ingat/keys/fx-lite/{id_ed25519,known_hosts}, mode 0600

   [params]
   FXLITE_IMAGE = "ghcr.io/<owner>/fx-lite@sha256:<digest>"   # the CI-built image of the release; required by fx-lite
   FXLITE_PORT = "20090"                # leave the key out and a port is allocated from 20000-29999

   [app_env]
   ALLOWED_ORIGINS = "https://lite-test.example.internal"
   BASE_URL = "https://lite-test.example.internal"
   MAIL_SENDER = "lite-test@example.invalid"
   PROXY_ADDRESS = "127.0.0.1"

   [backups]
   keep_daily = 7
   keep_weekly = 4
   ```

2. For an `ssh://` repository, place the read-only deploy key and a pinned `known_hosts` under `INGAT_ROOT/keys/<key>/`.
3. Optional: `ingat validate /srv/ingat/inbox/<checkout> --instance /srv/ingat/inbox/lite-test.toml`.
4. `ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0`, then type `lite-test` to approve. It fetches the source, reads the manifest at that ref, allocates ports, generates the declared secrets and prints `next: ingat deploy lite-test v1.2.0`.
5. Secrets the manifest declares as env-file secrets (for example mail credentials) are set with `ingat secret set` from M2. In M1, after `init` (which creates `secrets/env/` with mode 0700) and before the first deploy, place each value as a file `INGAT_ROOT/instances/lite-test/secrets/env/<KEY>` (mode 0600, no trailing newline); a later `init` re-run keeps a file that already exists.

Instance names are lowercase, at most 30 characters: a letter first, then letters, digits and single hyphens, never at the start or the end. `ingat list` shows the instances of this host.

## 4. First deploy

```sh
ingat deploy lite-test v1.2.0
```

Without a prepared candidate the command prepares first (pull and pin the images: class B, no approval), then prints the deploy plan, one numbered step per line with its class and the forward point, and asks you to type the instance name. Then it prints two timestamped lines per step (`started`, then `done` or the failure phase) and a final `operation <outcome>` line. The outcomes:

- `completed`, exit 0: the instance runs; `next: ingat status lite-test`.
- `paused`, exit 4: the app's install pause. The message says what to do (for `fx-lite`: copy the bootstrap file into `INGAT_ROOT/inbox/`, run `ingat task lite-test bootstrap-config --input config=<file>`, finish the setup in the browser), then `ingat resume lite-test` and type the name again.
- `failed-unchanged`, exit 3: a step failed before anything changed for good; everything it started was stopped again. Read the message, fix the cause, run the same command again.
- `failed-frozen`, exit 3: a step after the app's migrate failed (for `fx-lite` the install migrate is the forward point). The instance is frozen with its writers stopped and `next` is this same `deploy` command, which continues on the generation the install created (section 7).
- `needs-review`, exit 4: the undo of a failure did not complete. Read `ingat history lite-test` and the warnings in the result before anything else.
- exit 130: cancelled before any effect.

`ingat deploy` needs a terminal: a job without one is refused with exit 2 before anything is prepared.

## 5. Day to day

| Task | Command | Notes |
|---|---|---|
| See the state | `ingat status lite-test` | exit 5 means attention; the last line `next:` names the command to run. `ingat status` with no name covers every instance |
| Deeper checks | `ingat doctor lite-test` | policy, gate, secrets, port collisions, roots |
| Containers, logs, past operations, backups | `ingat ps lite-test`, `ingat logs lite-test app --since 1h`, `ingat history lite-test`, `ingat bundles lite-test` | read-only, never write |
| Manual backup | `ingat backup lite-test --reason "before the mail change"` | class B, no approval; stops writers unless every store backs up online |
| Verify a bundle | `ingat verify lite-test --latest` | re-hashes the bundle and runs the app's verify tasks |
| Restore drill | `ingat verify lite-test --latest --restore-test` | restores the bundle into an isolated throwaway copy, checks it, tears it down; marks the bundle `restore-tested` |
| Retention | `ingat prune lite-test --bundles`, then with `--apply` | a dry run first; `scheduled backup` applies retention on its own |
| Stop, start, restart | `ingat stop lite-test`, `ingat start lite-test`, `ingat restart lite-test` | class C: type the name each time |
| A declared app task | `ingat task lite-test queue-status`, `… --arg job=<id>`, `… --input config=<file>` | class B for a `read` task, class C (type the name) for an `app-write` or `data` task: all of `fx-lite`'s `queue-*` and `bootstrap-*` tasks are class C and refuse while the instance is frozen. Input files live in `INGAT_ROOT/inbox/`; a task that prints to the terminal is never recorded; an `app-write` task whose exit is not the declared `ok` closes `needs-review` (exit 4) |
| Update | `ingat deploy lite-test v1.3.0` | see below |

**Updates.** A deploy that changes only configuration recreates exactly the changed services. A deploy that changes the image of a writer, or any image of an app that migrates at start, is data-changing: the plan shows `Stop` of the writers, a `pre-change` bundle, its verification, the `migrate` task marked `forward point`, then the activation. Writers are stopped from the `Stop` step until the activation reopens writes; plan the downtime window. If a step after the forward point fails, the operation ends `failed-frozen` (exit 3) and prints the same `deploy` command as `next`. Running it again continues from the verified pre-change bundle when the app's migrate task is declared `idempotent` (as `fx-lite`'s is) and that bundle is still catalogued and `verified`; otherwise the deploy refuses `frozen`, and the way back is the restore of that bundle, which arrives in M2 (`ingat status lite-test` then names `history`).

## 6. Scheduled jobs

Create these in the host scheduler as root, by absolute wrapper path, with mail on a non-zero exit (DSM Task Scheduler: "send run details by email only when the script terminates abnormally"):

| When | Command |
|---|---|
| daily 01:30 | `/srv/ingat/bin/ingat scheduled backup lite-test` |
| daily 03:00 | the off-host copy of `/srv/ingat-backups` by your own tool (restic, borg, rsync; Hyper Backup on DSM) |
| Sunday 05:00 | `/srv/ingat/bin/ingat scheduled verify lite-test --latest --restore-test` |
| hourly | `/srv/ingat/bin/ingat scheduled status` |

`scheduled backup` prints one line on success and applies retention; `scheduled status` prints nothing and exits 0 unless the attention set changed since its last run, so a lasting condition mails you once. A busy lock exits 2 and is mailed: keep job times apart. `scheduled` refuses anything that needs typed approval.

## 7. When something goes wrong

- **The SSH session dropped during an operation.** For every executor-run operation (deploy, backup, verify, drill, start, stop, restart, resume, abandon) nothing stopped: it runs in a detached executor. Reconnect and run `ingat attach lite-test` to follow it to the end. A terminal task (`bootstrap-config`, `bootstrap-new-code`) runs in the CLI itself: after a drop, run the next command and, if it prints `task-running`, the exact `docker stop` it names, then `ingat status lite-test`. Ctrl-C in a followed operation asks `[d]etach or [c]ancel?`, and detaching never stops the operation; in a terminal task Ctrl-C is a cancel request.
- **`status` shows `attention: open-operation: operation <n> (<kind>) is interrupted` (or `paused`), exit 5.** `ingat resume lite-test` continues from the first unfinished step; `ingat abandon lite-test` undoes what can be undone and closes it. `status` names the right one as `next`. (A follower that finds the executor gone exits 4 with the same code; `status` is then the next command.) An interrupted `prepare`, `backup`, `verify` or drill is abandoned automatically by the next command that opens an operation on the instance (a backup, deploy, start …); until then `status` still shows it. If that automatic abandon could not undo everything, the new command refuses `needs-review`: run `ingat status lite-test` and follow its `next`.
- **`task-running`.** A task container of the operation is still alive. Run the exact `docker stop <container>` the message prints, then `resume` or `abandon`.
- **`failed-frozen`.** The instance is frozen with writers stopped. The way forward is the `deploy` command the result printed (same ref, same candidate), under the conditions in section 5; `backup`, `start`, `stop`, `restart` and write tasks refuse while frozen, while read tasks, `verify` and the drill still run.
- **`uncertified`.** The OS, kernel or Engine changed since the last certification: `ingat selftest --host`.
- **`changed-outside` or `foreign`.** Something outside Ingat changed or added containers, networks or volumes of the project. Never use a vendor GUI's project actions (Container Manager "Clean" or "Delete") on an Ingat project. Remove what you added by hand; `ingat restart lite-test` brings the recorded deployment back. If images are gone, `ingat prepare lite-test <current ref>` re-pulls them by their recorded digests.
- **`not a tested combination`.** See section 1: pin the Engine, or wait for a tool release that tests the new line.
- **`… lock is busy: op …` or `container ingat-exec-lite-test is still present`, exit 2.** Another command holds the instance, or the host lock for `init` and `selftest --host`; `ingat attach lite-test` follows an instance operation, otherwise wait for the holder the message names.

Exit codes: 0 completed, 1 refused (nothing changed), 2 could not run (nothing changed), 3 failed after effects (a recorded safe state), 4 needs attention (paused, interrupted, unknown, needs review), 5 findings, 130 cancelled before any effect. Every command also accepts `--json` for one JSON object instead of lines.

## 8. Upgrade the tool

Run `sh install.sh --version <new>` again as root. It refuses while any operation is open (exit 2), runs `ingat selftest --host` with the new image and keeps the current wrapper if that fails (exit 3); otherwise it replaces the wrapper and keeps the old one as `bin/ingat.prev`, which is the way back.

## 9. Never do this

- `docker compose down -v`, `docker system prune`, `docker volume rm`, or a vendor GUI's project actions on an Ingat project: Ingat cannot prevent them and would only report the damage.
- Edit anything under `INGAT_ROOT` except `instances/<i>/instance.toml`, the secret files you place in M1, `inbox/` and `keys/`.
- Put `INGAT_ROOT` or a bind store on a network share, a synchronized folder or (on DSM) a shared folder.
- Run two tool versions on one host, or copy the roots to another host by hand (cross-host restore arrives in M4).
- Look for a `--force` or `--yes`: there is none. The only way past a refusal is the command the message names.
