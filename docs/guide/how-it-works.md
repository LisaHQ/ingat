# How Ingat works

**English** · [Tiếng Việt](how-it-works.vi.md)

What Ingat does, who it is for, and how it keeps your data safe, in plain words.

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
- **App developers** who want their app to be easy and safe to install and update. They add one file, `ingat.toml`, to the app's repository ([how](../app-developers/MANIFEST_SPEC.md)).
- **AI assistants that run servers for their owner.** Ingat is built as a safety harness for them: they may look around and take backups freely, but a change needs the owner's approval, and anything that can lose data can only be approved by a person typing at a real terminal. This holds for assistants that follow the rule; their own tool settings enforce it. The way for an owner to hand an approved plan to an assistant comes in M2.

## Why your data is safe

| Promise | What it means for you |
|---|---|
| **A backup before every risky change** | Before an update that touches your data, Ingat stops the parts of the app that change your data, makes a backup copy, seals it with checksums and checks it. Only then does it change anything. If the backup fails, nothing is replaced. |
| **Nothing is written over** | A restore fills a new, separate data area and only then switches the app over to it. Your previous data stays as it was. (Restores come in M2; the rule is already part of the design.) |
| **Backups are proven, not hoped for** | A backup copy counts as "test-restored" only after Ingat restored that exact copy into a separate test copy of the app, which cannot reach your live data, and the app's own checks passed. |
| **Interruptions are safe** | Changes run in a helper on the machine, not in your SSH window, so a dropped connection stops nothing. The one exception is a task that talks to you in the terminal (for example a setup step of a first install): it runs from your window, so if the connection drops, run your next command and follow what it says ([operator guide §8](operator-guide.md#8-when-something-goes-wrong)). Ingat writes down each step before it takes it, so an interrupted job can always be continued or undone. |
| **It deletes only its own things** | Ingat removes only what it created, can prove it owns, and listed in a plan first. It never runs `docker system prune` or `docker compose down -v`, and it never touches containers, volumes or networks it did not create. |
| **Passwords stay private** | Passwords and keys live only in files that only root can read. Ingat never puts them on a command line, in its records, in backups, in logs or in error messages. |
| **No "force" switch** | There is no `--force` and no `--yes`. When Ingat says no, nothing has changed, and the message names the safe command to run instead. |
| **Only on tested machines** | Commands that change anything run only on Docker versions this release was tested with, and only after Ingat has tested your machine (`ingat selftest --host`). |

The exact rules are the 17 safety floors in [`docs/design/LIFECYCLE.md`](../design/LIFECYCLE.md#1-safety-floors). They are written in code, and no setting turns them off.

## How it works, in short

- Ingat is one pinned container image (`linux/amd64` and `linux/arm64`) with Python, the Docker command line, Compose and git inside, started by a 20-line root-only script. A server, a VPS and a NAS run exactly the same bytes; the Python and Compose of the machine itself are never used.
- Every change runs in a separate helper container (`ingat-exec-<instance>`), so a dropped SSH session or a scheduled job can never stop a data update half-way. The command you typed only plans, asks for approval and follows along. The exceptions are tasks that talk to you in the terminal, which run from your own window, and three short commands that only change Ingat's own records (`host init`, `init`, `secret set`).
- Compose always runs on the app's own Compose files plus a file Ingat generates, which pins every service to the exact recorded image and adds labels that never change between deployments, so an update recreates only the services whose settings changed.
- Each app keeps the knowledge of its own data in its own images. Its `ingat.toml` lives in the app's repository, is read from the exact version being installed, and declares its tasks (backup, restore, check, data update) and what each exit code means.
- A database counts as ready only after the readiness check the app declares for it has passed, not merely because its container has started.
- Every operation keeps a step log: each step is written down before it runs, and checked before it is retried. Only one operation per app may be open at a time.

The full design: [`docs/design/ARCHITECTURE.md`](../design/ARCHITECTURE.md) and [`docs/design/LIFECYCLE.md`](../design/LIFECYCLE.md).

