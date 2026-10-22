# ADR-0002 Synthesis basis: lean structure, safety floors, DSM-native execution

**Status:** Accepted.

**In plain words:** Three draft designs were compared. Ingat takes the smallest one as its base, and adds the strongest safety rules of the second and the way the third runs on a NAS.

## Context

Three proposals were judged under two lenses. Lens A (safety, correctness, host reality) chose `safety` (43) over `container` (43, tie) and `lean` (41). Lens B (one owner with AI agents, time to first use) chose `lean` (49) over `safety` (44) and `container` (43). Combined: lean 90, safety 87, container 86. Each judge listed must-fix defects for its winner and grafts from the others.

## Decision

Use **lean** as the structural base (smallest surface: one data strategy, a closed set of step types, 600-line modules, app files plus a generated override, the isolated `--r<seq>` restore project, the app's own bundle-name grammar, real contact with the target host from M0). Graft **safety**'s floors and consumer coverage (stable TCP store readiness, deterministic task containers, log snapshots, owner-gated and forbidden env keys, declarative smoke reproducing the PostgreSQL consumer's shell smoke test, class D terminal challenge, lineage field, exact exit maps). Graft **container**'s DSM execution and storage model (detached executor, all task I/O in a plain POSIX root with copy-then-rename into the share, the probe volume for Docker-root space, undeclared non-zero exits of write tasks as `unknown`, tiered version gate, auto-abandon of scratch-only operations, `conformance` in app CI). Every must-fix defect from both lenses is resolved; the defect-by-defect traceability stays in the private design record.

## Alternatives

Take `safety` whole (rejected: about 13 slices before the PostgreSQL consumer's staging, three task modes, a re-rendered model that risks escape drift). Take `container` whole (rejected: 19 slices, a hand-written `extends`/`!reset` derived-service emitter, a backup id that breaks the PostgreSQL consumer's backup-name grammar, `--approve` usable for purge).

## Consequences

MVP is about 5.5k runtime lines (5.2k Python) in 7 slices ([ROADMAP.md](../ROADMAP.md)), larger than lean's 4.8k because of the executor, readiness, smoke, owner-gated keys and the review fixes. The first real consumer (the SQLite consumer's test instance, `lite-test`) runs on the target host at the end of M1, within about 3k lines; the PostgreSQL consumer's staging (`pg-staging`) follows at the end of M2.
