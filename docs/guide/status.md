# Ingat status and roadmap

**English** · [Tiếng Việt](status.vi.md)

What works today, what is tested, what is not done yet, and what comes next.

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
- The first real machine, a Synology NAS on DSM 7.4.1 with Container Manager 24.0.2-1706 (`x86_64`), passed `ingat selftest --host` with version 0.1.0 (22 checks). Its [certification](../../src/ingat/support/hosts/dsm-7.4.1-90080-0-containermanager-24.0.2-1706-4.4.302+-x86_64.json) is committed; the manual items of its checklist are still open.

**Not done yet:**

- Release v0.1.0 is a draft, not published. Its image `ghcr.io/lisahq/ingat:0.1.0` is public.
- No real app runs under Ingat yet. The first one, `lite-test` (the SQLite consumer) on that NAS, completes milestone M1; the M1 exit gate has not passed. M2 comes next.
- An upgrade from one real release to the next is not tested yet: until a second release exists, the test upgrades between two builds of the same version.
- Not in this version: restores; apps with Docker volumes or a separate database service; apps deployed from an image only; `exec` tasks; `secret set`; the plan hand-over for AI assistants; commands that can lose data (class D); a few app manifest features (file streams, log snapshots, deploy pre- and post-checks, a task-based `[schema]`); and `doctor`'s comparison of the proxy address it sees with the configured one.

**Decided, not built yet:**

- **Data providers** ([ADR-0031](../design/adr/0031-data-providers.md)): an app lists its data sets (PostgreSQL, MySQL, MariaDB, SQLite, plain files), and Ingat's own pinned helper images back them up, check them and restore them, so an app needs no backup commands of its own. A public catalog of certified apps. The public contract that provider images follow, and the first images, come alongside M2, the rest right after the M2 exit gate.
- **`ingat ui`** ([ADR-0032](../design/adr/0032-local-session-bound-web-view.md)): a read-only web page for your session, open only on the machine itself, with plain explanations and a helper that writes the command for you. Its first version has no access to Docker. It comes after the M2 plan hand-over.
- **`ingat report` and `ingat support-bundle`** ([ADR-0033](../design/adr/0033-commercial-boundary-report-and-hosted-service.md)): one outbound status summary that you sign up for, and a package of facts to share when you ask for help. With M2 or M3.

**Free, and it stays free.** Ingat is open source under the Apache License 2.0. Nothing that keeps or recovers your data will ever be paid, limited or tied to a plan. A hosted status page may become a paid service later ([ADR-0033](../design/adr/0033-commercial-boundary-report-and-hosted-service.md)).

## Roadmap at a glance

| Milestone | What it brings | State |
|---|---|---|
| M0 Decisions and machine facts | Name and namespace, facts about the first machine, runtime checks, where app images are built | In progress |
| M1 First real app | `lite-test` (the SQLite consumer) on the first machine, a Synology NAS; CI covers plain Linux | In progress: code done, exit gate open |
| M2 Restores and the PostgreSQL consumer | Restores into a new data area for both apps; `pg-staging` on the first machine; plan hand-over to AI assistants; the `ingat.toml` format frozen | Next |
| M3 Ready for production | Going back to an older version, removing an app, cleaning up, monitoring, helpers for systemd, cron and DSM schedules; `pg-prod` (when owner decision OD-5 allows) | Planned |
| M4 Disaster recovery and taking over apps | Restore on another machine, import, taking over an app installed without Ingat; certification of a plain Linux server (once such a server is available) | Planned |
| M5 Ingat upgrades itself | Self-upgrade and record migration commands | When needed |

Details, sizes and exit gates: [`docs/design/ROADMAP.md`](../design/ROADMAP.md).
