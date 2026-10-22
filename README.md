# Ingat

**English** · [Tiếng Việt](README.vi.md)

[![CI](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LisaHQ/ingat/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

**Install, update and back up the apps you run with Docker Compose on your own server or NAS, without ever gambling with your data.**

Ingat is a small command-line tool for one machine: a home server, a VPS, a small board or a NAS that runs Docker. It installs your apps from an exact version, updates them, backs them up every night, and proves each backup by restoring it into a separate test copy. Every change that could touch your data starts with a checked backup. *Ingat* means "remember, be careful" in Malay and Indonesian, and "take care!" in Tagalog.

## Highlights

- **A backup before every risky change.** Before an update touches your data, Ingat stops the parts of the app that write data, makes a sealed backup and checks it. If the backup fails, nothing is replaced.
- **Backups you can trust.** A backup counts as test-restored only after Ingat restored that exact copy into a separate test copy of the app and the app's own checks passed.
- **Never writes over your data.** A restore fills a new data area and keeps the old one (restores arrive in M2).
- **Safe when your connection drops.** Almost every change runs in a helper on the machine, not in your SSH window, and each step is written down first, so an interrupted job can be continued or undone.
- **Touches only what it owns.** No `docker system prune`, no `down -v`, no `--force`: Ingat deletes only what it created and listed in a plan.
- **Plain words.** Every message says what happened and which command comes next. Reading and backups run unattended; every change waits for your typed approval.

## Quick start

You need Linux with a Docker Engine version this release is tested with (24.0 or 29.9 on `x86_64`, 29.9 on `arm64`) and root access. Download `install.sh`, `facts.sh` and `SHA256SUMS` from the [release page](https://github.com/LisaHQ/ingat/releases) into one folder (v0.1.0 is still a draft, so this works once it is published), then:

```sh
sudo -i
cd /path/to/downloads                                       # the folder with the release files
sh install.sh --version 0.1.0 --link /usr/local/bin/ingat   # on a Synology NAS add --root /volume1/ingat --backups /volume1/ingat-backups
ingat host init                                             # type the name the hostname command prints
ingat selftest --host                                       # tests this machine; takes a few minutes
```

Then describe your app in an instance file in Ingat's inbox (`/srv/ingat/inbox/`, on a NAS `/volume1/ingat/inbox/`) and install it:

```sh
ingat init lite-test --config /srv/ingat/inbox/lite-test.toml --ref v1.2.0
ingat deploy lite-test v1.2.0                               # shows the plan; type lite-test to approve
ingat status lite-test
```

The [operator guide](docs/guide/operator-guide.md) walks through each step, the Synology NAS setup, the instance file and the nightly backups.

## Documentation

- **Running Ingat:** the [operator guide](docs/guide/operator-guide.md), [all commands](docs/guide/commands.md), [where it runs](docs/guide/where-it-runs.md), [how it keeps your data safe](docs/guide/how-it-works.md), [words used](docs/guide/glossary.md), [status and roadmap](docs/guide/status.md).
- **Making your app work with Ingat:** the [`ingat.toml` and `instance.toml` files](docs/app-developers/MANIFEST_SPEC.md) and the [onboarding checklist](docs/design/ARCHITECTURE.md#113-generality-rule).
- **Contributing, or developing Ingat with an AI agent:** [`CLAUDE.md`](CLAUDE.md) first, then the [architecture](docs/design/ARCHITECTURE.md), the [lifecycle and safety floors](docs/design/LIFECYCLE.md), the [roadmap](docs/design/ROADMAP.md), the [decision records](docs/design/adr/README.md) and the [conventions and names](docs/design/CONVENTIONS.md).

Every Markdown document except `CLAUDE.md` has a Vietnamese version beside it (`<name>.vi.md`); English is the reference.

## Status

Early. v0.1.0 is the first test release, still a draft. CI passes on real Docker (Engine 24.0 and 29.9 on `x86_64`, 29.9 on `arm64`), and the first real machine, a Synology NAS on DSM 7.4.1, passed `ingat selftest --host`. Milestone M1 is not finished until the first real app runs there; restores come in M2. More: [status and roadmap](docs/guide/status.md).

## License

[Apache License 2.0](LICENSE). Ingat is free and stays free: nothing that keeps or recovers your data will ever be paid, limited or tied to a plan.
