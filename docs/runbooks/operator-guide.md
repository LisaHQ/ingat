# Ingat operator guide

**English** · [Tiếng Việt](operator-guide.vi.md)

This guide is for the person who runs Ingat on a machine: you install it, add your apps, and keep them backed up and up to date. It says what to type and what you will see. The reasons behind each rule are in [`LIFECYCLE.md`](../LIFECYCLE.md) and [`ARCHITECTURE.md`](../ARCHITECTURE.md).

It covers version 0.1.0 (milestone M1), the commands that exist in code today ([README](../../README.md#everyday-use)). Restores, approvals for commands that can lose data (class D), `secret set` and handing a plan to an AI assistant (`plan`/`apply`) arrive in M2 ([`ROADMAP.md`](../ROADMAP.md)); this guide says so where it matters.

**How to read the examples.** Run every command as the machine's administrator user, root. `ingat` stands for the `ingat` command that the installer writes: `/srv/ingat/bin/ingat` with the default folders, or `/volume1/ingat/bin/ingat` on a Synology NAS. `lite-test` is an example instance (one installed copy of an app) of the sample app `fx-lite`.

**A few words you will meet:**

- **instance:** one installed copy of an app, with its own name, such as `lite-test`.
- **writers:** the parts of the app that change your data.
- **backup copy:** a sealed backup of one instance (Ingat's records call it a *bundle*).
- **`INGAT_ROOT`:** Ingat's own folder. **`INGAT_BACKUPS`:** the folder with the backup copies.

## 1. Before you start

- **The machine.** You need a Linux Docker Engine 24.0 or later with the `docker compose` plugin, reachable as root through the local socket; SSH with `sudo -i`; a scheduler that emails you when a job fails (systemd timers, cron, or Task Scheduler on a Synology NAS); and a tool that copies the backups to another place (restic, borg, rsync, or Hyper Backup on a Synology NAS). Details: [`ARCHITECTURE.md`](../ARCHITECTURE.md#114-minimum-host-requirements) §11.4.
- **Two folders.**
  - `INGAT_ROOT` holds Ingat's own records and the live data of apps that keep their data in plain folders. Default `/srv/ingat`. It must belong to root with permissions `0700`, so only root can open it, and it must sit on a disk inside this machine, never on a network share.
  - `INGAT_BACKUPS` holds the finished backup copies. Each one is sealed with checksums, so any later change to it is noticed. Default `/srv/ingat-backups`. Only root writes there, and this is the folder your off-site copy is taken from.
  - On a Synology NAS, pass `--root /volume1/ingat --backups /volume1/ingat-backups` when you install. Never accept the `/srv` defaults there.
- **Ingat can see only these two folders.** It runs inside its own container, which is shown `INGAT_ROOT` and `INGAT_BACKUPS` and nothing else on the machine. So every file path you give it (`init --config`, `validate <repo-dir>`, `validate --instance`, task `--input` files) must be a full path inside one of them, or Ingat cannot find the file. Put such files, and app checkouts, in the inbox: `INGAT_ROOT/inbox/`.
- **Your app** needs an `ingat.toml` in its repository and images built by its CI ([`MANIFEST_SPEC.md`](../MANIFEST_SPEC.md); the onboarding checklist in [`ARCHITECTURE.md`](../ARCHITECTURE.md#113-generality-rule) §11.3). `ingat validate <repo-dir>` checks a checkout offline, without changing anything, for example one under `INGAT_ROOT/inbox/`.
- **Keep Docker on a tested version.** Commands that change anything run only on a Docker Engine version line that this release of Ingat was tested with (the list ships inside Ingat as `tested.json`), and only after the machine check in section 2, which you repeat after every update of the machine. On any other Docker version, `ingat status` says `not a tested combination of this release`: you can still look at everything and take backups that do not stop the app, but every command that changes the app or its data refuses. So stop Docker from updating by itself: on a Linux machine, pin `docker-ce` (`apt-mark hold`), and move to a newer Docker only together with an Ingat release that was tested with it.

## 2. Install Ingat and check your machine

Do this once per machine. As root, with the release's `install.sh`, `facts.sh` and `SHA256SUMS` in one folder:

```sh
sudo -i
cd /path/to/downloads   # the folder where you saved the release files
sh install.sh --version 0.1.0          # default folders; add --root and --backups on a Synology NAS
ingat host init                        # links Ingat to this Docker; type the name the hostname command prints, to approve
sh facts.sh > facts.json               # writes down facts about this machine (changes nothing); keep the file with your notes
ingat selftest --host                  # tests Ingat on this machine: one summary line, then nothing until done (minutes)
ingat status                           # "gate tier 2 (everything)" in the last lines: Ingat may now make changes here
```

On a Synology NAS, give `facts.sh` the same folders: `sh facts.sh --root /volume1/ingat --backups /volume1/ingat-backups > facts.json`.

**What you will see.**

- `install.sh` prints the lines of its offline self-check and `installed version …`.
- `host init` prints the Docker version, storage driver and kernel, then, after any `risk:` lines, either `this computer's Docker build is certified, so every command may run (gate tier 2)` or `changes are not allowed on this computer yet (gate tier 2 refuses): …` followed by the reason.
- `selftest --host` prints one `PASS` line per check and the path of the certificate file it wrote.

**After every update of the operating system, the kernel or Docker**, run `ingat selftest --host` again. Until you do, `ingat status` shows a `needs your attention (uncertified)` line, and the scheduled test restore refuses to run (exit 2). The nightly backups keep running as long as the app can be backed up without stopping (as `fx-lite` can), but they keep every old backup copy until you run `ingat selftest --host` again.

**No internet on the machine?** `sh install.sh --version 0.1.0 --from-tar ingat-0.1.0-amd64.tar` loads Ingat from the release file instead of downloading it (on an `aarch64` machine, use `ingat-0.1.0-arm64.tar`). Download the file from the same release page on another computer and copy it into the same folder.

## 3. Add your app

1. **Write the instance file** into the inbox, for example `/srv/ingat/inbox/lite-test.toml`. All keys and a full example: [`MANIFEST_SPEC.md`](../MANIFEST_SPEC.md) §6 and §12. The minimum for `fx-lite`:

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
   FXLITE_PORT = "20090"                # leave the key out and a port is picked from 20000-29999

   [app_env]
   ALLOWED_ORIGINS = "https://lite-test.example.internal"
   BASE_URL = "https://lite-test.example.internal"
   MAIL_SENDER = "lite-test@example.invalid"
   PROXY_ADDRESS = "127.0.0.1"

   [backups]
   keep_daily = 7
   keep_weekly = 4
   ```

2. **For a repository reached over `ssh://`**, put its read-only deploy key and a pinned `known_hosts` file in `INGAT_ROOT/keys/<key>/`.
3. **Optional check:** `ingat validate /srv/ingat/inbox/<checkout> --instance /srv/ingat/inbox/lite-test.toml`.
4. **Register the instance:** `ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0`, then type `lite-test` to approve. Ingat downloads the app's source at version `v1.2.0`, reads the app's `ingat.toml` from it, picks any network port you left out, and creates the passwords the app says it can make up itself (you never see or type those; the ones you must supply are in step 5). It ends with `next: ingat deploy lite-test v1.2.0`.
5. **Passwords you supply yourself.** Some secrets the app declares, for example mail credentials, come from you. From M2 you set them with `ingat secret set`. In M1, after `init` (which creates `secrets/env/` with mode 0700) and before the first deploy, put each value in a file `INGAT_ROOT/instances/lite-test/secrets/env/<KEY>`, with mode 0600 and no newline at the end. Running `init` again later keeps a file that already exists.

**Instance names** are lowercase and at most 30 characters: a letter first, then letters, digits and single hyphens, never a hyphen at the start or the end. `ingat list` shows the instances on this machine.

## 4. Install the app

```sh
ingat deploy lite-test v1.2.0
```

**What happens.**

1. If this version is not prepared yet, Ingat prepares it first: it downloads the app's images (the packaged program files) and records exactly which ones it got. This changes nothing in a running app, so it needs no approval.
2. Ingat prints the plan: one numbered line per step, with how risky the step is (its class). One step is marked `forward point`: after it, Ingat can no longer simply undo the change.
3. You type the instance name (`lite-test`) to approve.
4. While it runs, each step prints two lines with the time: `started`, then `done` (or the stage where it failed). The last line reads `operation <outcome>`.

**How it can end.**

| Outcome | Exit | What it means and what to do |
|---|---|---|
| `completed` | 0 | The app runs. `next: ingat status lite-test`. |
| `paused` | 4 | The app's install pause. The message says what to do. For `fx-lite`: copy the bootstrap file into `INGAT_ROOT/inbox/`, run `ingat task lite-test bootstrap-config --input config=<file>`, finish the setup in the browser, then run `ingat resume lite-test` and type the name again. |
| `failed-unchanged` | 3 | A step failed, but nothing changed for good: Ingat stopped everything it had started, and your app and data are as they were before. Read the message, fix the cause it names, then run the same command again. |
| `failed-frozen` | 3 | A step failed after the app had already updated its data (for `fx-lite`, that data update during install is the `forward point`). Ingat put the instance on hold ("frozen"): the writers stay stopped so nothing can be damaged. The `next:` line shows this same `deploy` command; running it again carries on from the data the install already created (section 8). |
| `needs-review` | 4 | Something failed and Ingat could not fully undo it on its own, so it needs you. Before you run anything else, read the warnings printed in the result and `ingat history lite-test`, which lists every past operation and how it ended. |
| cancelled | 130 | You cancelled before anything changed. |

`ingat deploy` must be typed by a person in a terminal, because it asks you to type the instance name. If a scheduled job or a script runs it, Ingat refuses (exit 2) before it changes or downloads anything.

## 5. Everyday tasks

| Task | Command | Notes |
|---|---|---|
| See the state | `ingat status lite-test` | Every line that starts with `needs your attention` is something that needs you; the command then ends with exit code 5. The last line, `next:`, is the command to run. `ingat status` with no name shows every instance on this machine. |
| Deeper checks | `ingat doctor lite-test` | Checks the app's settings against the safety rules, the machine's approval for changes, the secret files, port clashes and the folders. |
| Containers, logs, past operations, backups | `ingat ps lite-test`, `ingat logs lite-test app --since 1h`, `ingat history lite-test`, `ingat bundles lite-test` | These only read; they never write anything. |
| Make a backup now | `ingat backup lite-test --reason "before the mail change"` | No approval needed. While it runs, the writers are stopped, unless the app can back up all of its data while running (as `fx-lite` can). |
| Check a backup copy | `ingat verify lite-test --latest` | Checks that the backup copy is still exactly as it was written (no missing or damaged file) and runs the app's own checks on it, if the app has any. |
| Test-restore a backup copy | `ingat verify lite-test --latest --restore-test` | Proves the backup copy can really be restored: Ingat restores it into a separate, temporary copy of the app that cannot reach your live data, checks it, then removes that copy. Your running app is not touched. The backup copy is then marked `restore-tested`. |
| Remove old backup copies | `ingat prune lite-test --bundles`, then the same with `--apply` | The first command only lists which old copies the keep settings in your instance file (`keep_daily`, `keep_weekly`, `keep_monthly`) would remove; nothing is deleted until you add `--apply`. The nightly `scheduled backup` does this clean-up on its own. |
| Stop, start, restart | `ingat stop lite-test`, `ingat start lite-test`, `ingat restart lite-test` | Class C: type the name each time. |
| Run a task the app provides | `ingat task lite-test queue-status`, `… --arg job=<id>`, `… --input config=<file>` | See below. |
| Update to a new version | `ingat deploy lite-test v1.3.0` | Section 6. |

**About app tasks.**

- A task that only reads runs without approval. A task that changes the app or its data asks you to type the instance name. All of `fx-lite`'s `queue-*` and `bootstrap-*` tasks are of that kind, and they refuse to run while the instance is on hold (frozen).
- Put any input file in `INGAT_ROOT/inbox/`.
- A task that talks to you in the terminal shows its output only to you; nothing of it is saved.
- If a task that changes the app ends in a way the app did not declare (not its `ok` exit, and not one of its declared failures), Ingat cannot tell what the task did. It reports `needs-review` (exit 4): look at the result before you run anything else.

## 6. Updates

Run `ingat deploy lite-test v1.3.0`. What happens depends on what the new version changes.

- **Only settings change.** Ingat replaces only the parts of the app whose settings changed, and starts them with the new settings.
- **The data is touched.** This is the case when the new version changes the program of a writer, or of any part of an app that updates its data each time it starts. The plan then shows the safety steps:
  1. `Stop` the writers;
  2. take a `pre-change` backup copy;
  3. check that copy;
  4. run the app's data update (`migrate`, marked `forward point`: after this step Ingat can no longer simply go back);
  5. switch the app over to the new version.

  From the `Stop` step until the switch-over, the app does not accept changes, so pick a quiet time.

**If a step after the `forward point` fails**, the operation ends `failed-frozen` (exit 3). The app is put on hold with its writers stopped, and the `next:` line shows the same `deploy` command. Running it again carries on from the checked `pre-change` backup copy, provided two things hold:

- the app's data update is safe to run twice (its manifest says `idempotent`, as `fx-lite`'s does), and
- that backup copy is still listed and marked `verified`.

If not, the deploy refuses with `frozen`. The way back is then to restore that backup copy, which Ingat cannot do until M2; meanwhile `ingat status lite-test` points you to `history`.

## 7. Nightly and weekly jobs

Create these in the machine's scheduler as root, with the full path of the `ingat` command, and with an email when a job ends with a non-zero exit code. In DSM Task Scheduler, tick "send run details by email only when the script terminates abnormally".

| When | Command |
|---|---|
| daily 01:30 | `/srv/ingat/bin/ingat scheduled backup lite-test` |
| daily 03:00 | the off-site copy of `/srv/ingat-backups` by your own tool (restic, borg, rsync; Hyper Backup on a Synology NAS) |
| Sunday 05:00 | `/srv/ingat/bin/ingat scheduled verify lite-test --latest --restore-test` |
| hourly | `/srv/ingat/bin/ingat scheduled status` |

On a Synology NAS the command is `/volume1/ingat/bin/ingat` and the backups folder is `/volume1/ingat-backups`.

- `scheduled backup` prints one line when it succeeds, and removes old backup copies by the keep settings in your instance file (`keep_daily`, `keep_weekly`, `keep_monthly`), except while the machine is uncertified (section 2).
- `scheduled status` stays silent (exit 0) as long as nothing new needs your attention. It prints, and so the scheduler emails you, only when a problem appears or clears. A problem that lasts for days emails you once, not every hour.
- If one job starts while another is still running on the same instance, the second one stops with exit 2 and you get an email. Leave enough time between jobs.
- A scheduled job can never do anything that needs you to type an approval; it refuses instead.

## 8. When something goes wrong

**The SSH session dropped during an operation.** Nothing stopped. Every operation (deploy, backup, verify, test restore, start, stop, restart, resume, abandon) runs in a separate helper on the machine (its own container), not in your SSH window, so it carries on without you. Reconnect and run `ingat attach lite-test` to watch it to the end.

- The exception is a task that talks to you in the terminal (`bootstrap-config`, `bootstrap-new-code`). It runs from your window, so losing the window may leave it half done while its container keeps running. After a drop, run your next command; if it answers `task-running`, run the exact `docker stop` command it prints, then `ingat status lite-test`.
- While you watch an operation, Ctrl-C asks `[d]etach or [c]ancel?`. Detach only stops the watching, never the operation. In a terminal task, Ctrl-C asks the task to stop.

**`status` shows `needs your attention (open-operation): operation <n> (<kind>) was interrupted before it finished` (or `… is paused and waiting for you`), exit 5.** An operation started and has not finished: it was cut off (interrupted) or it is waiting for you (paused). You have two choices, and the `next:` line of `status` names the right one:

- `ingat resume lite-test` continues from the first step that did not finish;
- `ingat abandon lite-test` undoes what can be undone and closes the operation.

If `ingat attach` finds that the helper is gone, it ends with exit 4 and the same `open-operation` code; run `status` then. A cut-off prepare, backup, check or test restore is undone and closed automatically by the next command that starts an operation on this instance (a backup, a deploy, a start …); until then `status` keeps showing it. If that automatic clean-up could not undo everything, the new command refuses with `needs-review`: run `ingat status lite-test` and follow its `next:`.

**`task-running`.** A helper program (a task container) that the operation started is still running, and Ingat will not go on until it has stopped. Copy and run the exact `docker stop <container>` command the message prints, then `ingat resume lite-test` or `ingat abandon lite-test` (`ingat status lite-test` names the right one).

**`failed-frozen`.** The instance is on hold: the writers are stopped so nothing can be damaged. The way forward is the `deploy` command the result printed (same version, same prepared images), under the conditions in section 6. While on hold, `backup`, `start`, `stop`, `restart` and tasks that change the app or its data refuse to run; tasks that only read, `verify` and the test restore still work.

**`uncertified`.** The operating system, the kernel or Docker changed since the last machine check. Run `ingat selftest --host`.

**`changed-outside` or `foreign`.** Something other than Ingat (a person, another tool, or the Docker app's own buttons) changed, removed or added containers, networks or volumes in this instance's project. Never use a vendor app's project buttons (for example "Clean" or "Delete" in Container Manager) on an Ingat project. Remove by hand whatever you added; `ingat restart lite-test` puts the app back the way Ingat recorded it. If the app's images (program files) are gone, `ingat prepare lite-test <current ref>` downloads exactly the same ones again.

**`not a tested combination`.** See section 1: pin Docker to a tested version, or wait for an Ingat release that tests the new one.

**`Another command is still running and holds the lock …` (code `lock-busy`) or `container ingat-exec-lite-test is still present`, exit 2.** Another command is still working on this instance (or, for `init` and `selftest --host`, on this machine), and only one may work at a time. Nothing was changed. `ingat attach lite-test` lets you watch the running operation; otherwise wait for the command the message names to finish, then try again.

## 9. What the exit numbers mean

Every command ends with a number, its exit code. The scheduler and the `--json` output report it, and it tells you at a glance how the command ended.

| Exit | Meaning |
|---|---|
| 0 | Done. |
| 1 | Ingat said no and changed nothing (for example a wrong value or a safety rule). The message says why. |
| 2 | Ingat could not run and changed nothing (for example Docker not reachable, another command still busy, or no terminal to type an approval in). |
| 3 | The command stopped part-way after it had already changed something, but it left the app in a known safe state. `ingat status lite-test` shows what to do next. |
| 4 | The operation needs your attention: it is paused, it was cut off, Ingat could not tell how a step ended, or its clean-up did not finish. Run `ingat status lite-test`. |
| 5 | A check found something worth looking at; nothing failed. |
| 130 | You cancelled before anything changed. |

Add `--json` to any command to get the same answer as one block of machine-readable JSON, useful for scripts.

## 10. Upgrade Ingat

Put the new release's `install.sh` and `SHA256SUMS` in one folder, then run `sh install.sh --version <new>` again as root, with the same `--root` and `--backups` you installed with (on a Synology NAS: `--root /volume1/ingat --backups /volume1/ingat-backups`). Without them the installer uses the `/srv` folders and makes a second install instead of an upgrade.

1. It first downloads the new version.
2. If any operation is still unfinished, it stops and leaves the version you have untouched (exit 2).
3. Otherwise it runs `ingat selftest --host` with the new version. If that check fails, you keep the version you have (exit 3).
4. If it passes, the new version becomes the `ingat` command, and the old one is kept as `bin/ingat.prev`: your way back if the new version gives trouble.

## 11. Never do this

- Never run `docker compose down -v`, `docker system prune` or `docker volume rm`, and never use a vendor app's project buttons (such as "Clean" or "Delete"), on an Ingat project. These can destroy containers, images or data for good, and nothing brings them back. Ingat cannot stop them; afterwards it can only report that something is missing or changed.
- Never edit anything under `INGAT_ROOT` except `instances/<i>/instance.toml`, the secret files you place in M1, `inbox/` and `keys/`.
- Never put `INGAT_ROOT` or an app's data folder on a network share, a synchronized folder or (on a Synology NAS) a shared folder.
- Never run two Ingat versions on one machine, or copy Ingat's folders to another machine by hand (restoring on another machine arrives in M4).
- Never look for a `--force` or `--yes`: there is none. The only way past a refusal is the command the message names.
