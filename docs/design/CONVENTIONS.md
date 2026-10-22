# Conventions and names

**English** · [Tiếng Việt](CONVENTIONS.vi.md)

The conventions every Ingat document follows, and the names Ingat uses everywhere.

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

In code these names live only in `src/ingat/brand.py` and the wrapper template ([ADR-0003](adr/0003-name-namespaces-and-brand-module.md)); the docs use them literally.

