# Ingat operator guide (M1)

Status: describes the M1 command set as it exists in code ([`README.md`](../../README.md) "Commands (M1)"). Restores, class D approvals, `secret set` and the `plan`/`apply` hand-over to agents arrive in M2 ([`ROADMAP.md`](../ROADMAP.md)); this guide says so where it matters. The reasons behind every rule are in [`LIFECYCLE.md`](../LIFECYCLE.md) and [`ARCHITECTURE.md`](../ARCHITECTURE.md); this guide only says what to type and what you will see. A Vietnamese translation is at [`operator-guide.vi.md`](operator-guide.vi.md).

Every command is run as the machine's administrator user (root) through a small start script (`/srv/ingat/bin/ingat` with the default folders; `/volume1/ingat/bin/ingat` in the DSM profile, used on Synology NAS systems). Below, `ingat` stands for that path, and `lite-test` is an example instance (one installed copy of an app) of the sample app `fx-lite`.

## 1. Before you start

- **Host:** a Linux Docker Engine 24.0 or later with the `docker compose` plugin, reachable as root through the local socket; SSH with `sudo -i`; a scheduler that mails failures (systemd timers, cron, or DSM Task Scheduler); a tool for the off-host copy of the backups (restic, borg, rsync, or Hyper Backup on DSM). Details: [`ARCHITECTURE.md`](../ARCHITECTURE.md) §11.4.
- **Two folders:** `INGAT_ROOT` holds the tool's own records and the live data of apps that keep their data in plain folders (default `/srv/ingat`; it must belong to root with permissions `0700`, so only root can open it, and sit on a disk inside this machine, never on a network share). `INGAT_BACKUPS` holds the finished backup copies, each sealed with a checksum so any later change is noticed (default `/srv/ingat-backups`; only root writes there, and this is the folder your off-site copy is taken from). On DSM pass `--root /volume1/ingat --backups /volume1/ingat-backups` at install; never accept the `/srv` defaults there.
- **The tool can see only these two folders.** It runs inside its own box (a container) that is shown `INGAT_ROOT` and `INGAT_BACKUPS` and nothing else on the machine. So every file path you give it (`init --config`, `validate <repo-dir>`, `validate --instance`, task `--input` files) must be a full path that starts under one of them, or the tool cannot find the file; `INGAT_ROOT/inbox/` is the place to put such files and source checkouts.
- **Your app:** needs an `ingat.toml` in its repository and CI-built images ([`MANIFEST_SPEC.md`](../MANIFEST_SPEC.md); the onboarding checklist in [`ARCHITECTURE.md`](../ARCHITECTURE.md) §11.3). `ingat validate <repo-dir>` checks a checkout offline (for example one under `INGAT_ROOT/inbox/`).
- **Tested Docker versions:** commands that change anything run only on a Docker Engine version line that this release of the tool was tested with (the list ships inside the tool as `tested.json`), and only after the host check in section 2 (repeated after every update of the machine). On another Docker version `ingat status` says `not a tested combination of this release`: you can still look at the state and take backups that do not stop the app, but any command that changes the app or its data refuses. So keep Docker from updating by itself: on a Linux host pin `docker-ce` (`apt-mark hold`), and move to a newer Docker only together with a tool release that was tested with it.

## 2. Install and certify the host (once)

As root, with the release's `install.sh` and `SHA256SUMS` in one directory:

```sh
sudo -i
sh install.sh --version 0.1.0          # default roots; add --root and --backups for the DSM profile
ingat host init                        # binds the root to this engine; type the host name to approve
sh facts.sh > facts.json               # read-only host facts; keep the file with your notes
ingat selftest --host                  # certifies this platform build: one summary line, then nothing until done (minutes)
ingat status                           # "gate tier 2" among the last lines means this machine is approved for commands that change things
```

On the DSM profile pass the roots to `facts.sh` as well: `sh facts.sh --root /volume1/ingat --backups /volume1/ingat-backups > facts.json`.

What you will see: `install.sh` prints the lines of its offline self-check and `installed version …`; `host init` prints the Docker version, storage driver and kernel, then either `gate tier 2: this platform build is certified` (this machine's software is approved for commands that change things) or the reason it is not yet; `selftest --host` prints one `PASS` line per check and the path of the certificate file it wrote. Repeat `ingat selftest --host` after every operating-system, kernel or Docker update: until you do, `status` shows `uncertified` under `attention:` and the scheduled test restore refuses to run (exit 2), while the nightly backups keep running as long as the app can back up without stopping (as `fx-lite` can).

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
4. `ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0`, then type `lite-test` to approve. This downloads the app's source at version `v1.2.0`, reads the app's `ingat.toml` from it, picks any network port you left out, creates the passwords the app says it can make up itself (you never see or type those; the ones you must supply are in step 5), and prints `next: ingat deploy lite-test v1.2.0`.
5. Secrets the manifest declares as env-file secrets (for example mail credentials) are set with `ingat secret set` from M2. In M1, after `init` (which creates `secrets/env/` with mode 0700) and before the first deploy, place each value as a file `INGAT_ROOT/instances/lite-test/secrets/env/<KEY>` (mode 0600, no trailing newline); a later `init` re-run keeps a file that already exists.

Instance names are lowercase, at most 30 characters: a letter first, then letters, digits and single hyphens, never at the start or the end. `ingat list` shows the instances of this host.

## 4. First deploy

```sh
ingat deploy lite-test v1.2.0
```

If this version has not been prepared yet, the command prepares it first: it downloads the app's images (the packaged program files) and records exactly which ones it got. This part changes nothing in the running app, so it asks for no approval. Then it prints the plan: one numbered line per step, with how risky the step is (its class) and the step marked `forward point`, the point after which the tool can no longer simply undo the change. It asks you to type the instance name (`lite-test`) to approve. While it runs, each step prints two lines with the time (`started`, then `done`, or the stage where it failed), and the last line reads `operation <outcome>`. What each outcome means:

- `completed`, exit 0: the instance runs; `next: ingat status lite-test`.
- `paused`, exit 4: the app's install pause. The message says what to do (for `fx-lite`: copy the bootstrap file into `INGAT_ROOT/inbox/`, run `ingat task lite-test bootstrap-config --input config=<file>`, finish the setup in the browser), then `ingat resume lite-test` and type the name again.
- `failed-unchanged`, exit 3: a step failed, but nothing has changed for good: the tool stopped everything it had started, and your app and data are as they were before. Read the message, fix the cause it names, then run the same command again.
- `failed-frozen`, exit 3: a step failed after the app had already updated its data (for `fx-lite`, that data update during install is the `forward point`). The tool put the instance on hold ("frozen"): the writers, the parts of the app that change your data, stay stopped so nothing can be damaged. The `next:` line shows this same `deploy` command; running it again picks up from the data the install already created (section 7).
- `needs-review`, exit 4: something failed and the tool could not fully undo it on its own, so it needs your attention. Before you run anything else, read the warnings printed in the result and `ingat history lite-test`, which lists every past operation and how it ended.
- exit 130: cancelled before any effect.

`ingat deploy` must be typed by a person in a terminal window, because it asks you to type the instance name. If a scheduled job or a script runs it, the tool refuses (exit 2) before it changes or downloads anything.

## 5. Day to day

| Task | Command | Notes |
|---|---|---|
| See the state | `ingat status lite-test` | Every line that starts with `attention:` is something that needs you; the command then ends with exit code 5. The last line, `next:`, is the command to run. `ingat status` with no name shows every instance on this machine |
| Deeper checks | `ingat doctor lite-test` | policy, gate, secrets, port collisions, roots |
| Containers, logs, past operations, backups | `ingat ps lite-test`, `ingat logs lite-test app --since 1h`, `ingat history lite-test`, `ingat bundles lite-test` | read-only, never write |
| Manual backup | `ingat backup lite-test --reason "before the mail change"` | No approval needed. While it runs, the parts of the app that change your data are stopped, unless the app can back up every data store while it is running (as `fx-lite` can) |
| Check a backup copy | `ingat verify lite-test --latest` | Checks that the backup copy is still exactly as it was written (no missing or damaged file) and runs the app's own checks on it |
| Test restore | `ingat verify lite-test --latest --restore-test` | Proves the backup copy can really be restored: it restores it into a separate, temporary copy of the app that cannot reach your live data, checks it, then removes that copy. Your running app is not touched. The backup copy is then marked `restore-tested` |
| Remove old backup copies | `ingat prune lite-test --bundles`, then with `--apply` | The first command only lists which old copies would be removed by the keep settings in your instance file (`keep_daily`, `keep_weekly`, `keep_monthly`); nothing is deleted until you add `--apply`. The nightly `scheduled backup` does this clean-up on its own |
| Stop, start, restart | `ingat stop lite-test`, `ingat start lite-test`, `ingat restart lite-test` | class C: type the name each time |
| Run a task the app provides | `ingat task lite-test queue-status`, `… --arg job=<id>`, `… --input config=<file>` | A task that only reads runs without approval. A task that changes the app or its data asks you to type the instance name; all of `fx-lite`'s `queue-*` and `bootstrap-*` tasks are of that kind, and they refuse to run while the instance is on hold (frozen). Put any input file in `INGAT_ROOT/inbox/`. A task that talks to you in the terminal shows its output only to you; nothing of it is saved. If a task that changes the app ends in a way the app did not declare (not its `ok` exit, and not one of its declared failures), the tool cannot tell what the task did and reports `needs-review` (exit 4): look at the result before running anything else |
| Update | `ingat deploy lite-test v1.3.0` | see below |

**Updates.** If a new version changes only settings, the tool replaces only the parts of the app whose settings changed, and starts them with the new settings. If it changes the program of a part that writes to your data, or any part of an app that updates its data each time it starts, the update touches your data, and the plan shows the safety steps: `Stop` the writers (the parts of the app that change your data), take a `pre-change` backup copy, check that copy, run the app's data update (`migrate`, marked `forward point`: after this step the tool can no longer simply go back), then switch the app over to the new version. From the `Stop` step until the switch-over the app does not accept changes, so pick a quiet time for the update. If a step after the `forward point` fails, the operation ends `failed-frozen` (exit 3): the app is put on hold with its writers stopped, and the `next:` line shows the same `deploy` command. Running it again carries on from the checked `pre-change` backup copy, provided the app's data update is safe to run twice (its manifest says `idempotent`, as `fx-lite`'s does) and that backup copy is still listed and marked `verified`. If not, the deploy refuses with `frozen`; the way back is then to restore that backup copy, which this tool cannot do until M2 (`ingat status lite-test` points you to `history` in the meantime).

## 6. Scheduled jobs

Create these in the host scheduler as root, by absolute wrapper path, with mail on a non-zero exit (DSM Task Scheduler: "send run details by email only when the script terminates abnormally"):

| When | Command |
|---|---|
| daily 01:30 | `/srv/ingat/bin/ingat scheduled backup lite-test` |
| daily 03:00 | the off-host copy of `/srv/ingat-backups` by your own tool (restic, borg, rsync; Hyper Backup on DSM) |
| Sunday 05:00 | `/srv/ingat/bin/ingat scheduled verify lite-test --latest --restore-test` |
| hourly | `/srv/ingat/bin/ingat scheduled status` |

`scheduled backup` prints one line when it succeeds and removes old backup copies by the keep settings in your instance file (`keep_daily`, `keep_weekly`, `keep_monthly`). `scheduled status` stays silent (exit 0) as long as nothing new needs your attention; it prints and mails only when a problem appears or clears, so a problem that lasts for days mails you once, not every hour. If one job starts while another is still running on the same instance, the second one stops with exit 2 and you get a mail: leave enough time between jobs. A scheduled job can never do anything that needs you to type an approval; it refuses instead.

## 7. When something goes wrong

- **The SSH session dropped during an operation.** Nothing stopped. Every operation (deploy, backup, verify, test restore, start, stop, restart, resume, abandon) runs in a separate helper on the machine (its own container), not in your SSH window, so it carries on without you. Reconnect and run `ingat attach lite-test` to watch it to the end. The exception is a task that talks to you in the terminal (`bootstrap-config`, `bootstrap-new-code`): it runs from your window, so losing the window may leave it half done while its container keeps running. After a drop, run the next command; if it answers `task-running`, run the exact `docker stop` command it prints, then `ingat status lite-test`. While you are watching an operation, Ctrl-C asks `[d]etach or [c]ancel?`: detach only stops the watching, never the operation; in a terminal task, Ctrl-C asks the task to stop.
- **`status` shows `attention: open-operation: operation <n> (<kind>) is interrupted` (or `paused`), exit 5.** An operation was started and has not finished: it was cut off (interrupted) or is waiting for you (paused). You have two choices, and the `next:` line of `status` names the right one: `ingat resume lite-test` continues from the first step that did not finish; `ingat abandon lite-test` undoes what can be undone and closes the operation. (If `ingat attach` finds that the helper is gone, it ends with exit 4 and the same `open-operation` code; `status` is then the command to run.) A cut-off prepare, backup, check or test restore is undone and closed automatically by the next command that starts an operation on this instance (a backup, deploy, start …); until then `status` keeps showing it. If that automatic clean-up could not undo everything, the new command refuses with `needs-review`: run `ingat status lite-test` and follow its `next:`.
- **`task-running`.** A helper program (a task container) that the operation started is still running, and the tool will not go on until it has stopped. Copy and run the exact `docker stop <container>` command the message prints, then `ingat resume lite-test` or `ingat abandon lite-test` (`ingat status lite-test` names the right one).
- **`failed-frozen`.** The instance is on hold: the parts of the app that change your data are stopped so nothing can be damaged. The way forward is the `deploy` command the result printed (same version, same prepared images), under the conditions in section 5. While on hold, `backup`, `start`, `stop`, `restart` and tasks that change the app or its data refuse to run; tasks that only read, `verify` and the test restore still work.
- **`uncertified`.** The OS, kernel or Engine changed since the last certification: `ingat selftest --host`.
- **`changed-outside` or `foreign`.** Something other than Ingat (a person, another tool, or the Docker app's own buttons) changed, removed or added containers, networks or volumes that belong to this instance. Never use a vendor app's project buttons (for example Container Manager's "Clean" or "Delete") on an Ingat project. Remove by hand whatever you added; `ingat restart lite-test` puts the app back the way the tool recorded it. If the app's images (program files) are gone, `ingat prepare lite-test <current ref>` downloads exactly the same ones again.
- **`not a tested combination`.** See section 1: pin the Engine, or wait for a tool release that tests the new line.
- **`… lock is busy: op …` or `container ingat-exec-lite-test is still present`, exit 2.** Another command is still working on this instance (or, for `init` and `selftest --host`, on this machine), and only one may work at a time. Nothing was changed. `ingat attach lite-test` lets you watch the running operation; otherwise wait for the command the message names to finish, then try again.

Every command ends with a number called the exit code; the scheduler and the `--json` output report it, and it tells you at a glance how the command ended. 0: done. 1: the tool said no and changed nothing (for example a wrong value or a safety rule); the message says why. 2: the tool could not run and changed nothing (for example Docker not reachable, another command still busy, or no terminal window to type an approval in). 3: the command stopped part-way after it had already changed something, but it left the app in a known safe state; `ingat status lite-test` shows what to do next. 4: the operation needs your attention (it is paused, was cut off, the tool could not tell how a step ended, or its clean-up did not finish); run `ingat status lite-test`. 5: a check found something worth looking at; nothing failed. 130: you cancelled before anything changed. Add `--json` to any command to get the same answer as one block of machine-readable JSON (useful for scripts).

## 8. Upgrade the tool

Run `sh install.sh --version <new>` again as root. It first downloads the new version. If any operation is still unfinished it then stops and leaves the version you have untouched (exit 2). Otherwise it runs `ingat selftest --host` with the new version; if that check fails, you keep the version you have (exit 3). If it passes, the new version becomes the `ingat` command and the old start script is kept as `bin/ingat.prev`, which is the way back if the new version gives trouble.

## 9. Never do this

- `docker compose down -v`, `docker system prune`, `docker volume rm`, or a vendor app's project buttons (such as "Clean" or "Delete") on an Ingat project: these can destroy containers, images or data for good, and nothing brings them back. Ingat cannot stop them; afterwards it can only report that something is missing or changed.
- Edit anything under `INGAT_ROOT` except `instances/<i>/instance.toml`, the secret files you place in M1, `inbox/` and `keys/`.
- Put `INGAT_ROOT` or a bind store on a network share, a synchronized folder or (on DSM) a shared folder.
- Run two tool versions on one host, or copy the roots to another host by hand (cross-host restore arrives in M4).
- Look for a `--force` or `--yes`: there is none. The only way past a refusal is the command the message names.
