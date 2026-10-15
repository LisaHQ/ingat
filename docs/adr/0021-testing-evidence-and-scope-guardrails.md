# ADR-0021 Testing, evidence and scope guardrails

**Status:** Accepted; revised 2026-10-14, before any implementation, for platform-neutral host support ([ADR-0025](0025-host-baseline.md)): an arm64 lane joins the real-Docker gate.

## Context

About 1,100 offline tests of the predecessor, around a fake Docker of about 1k lines, missed six defects that real Docker found. Its real-Docker harness ran only on the owner's workstation and sat idle. Its runtime grew about tenfold, to about 29k lines, with no host run.

## Decision

Real Docker on every push (`docker:24.0.2-dind` and one exact `docker:29.Y.Z-dind` on `amd64`, plus an arm64 lane with the same 29.Y.Z tag on GitHub-hosted arm64 runners), the suites of [ARCHITECTURE.md](../ARCHITECTURE.md) §10.3, evidence only from CI runs and committed host certifications, one verdict vocabulary (`PASS`, `FAIL`, `BLOCKED`). Scope rules: every feature names a consumer need; the first milestone ends with a real consumer (the SQLite consumer's test instance, `lite-test`) on the first real host within about 3k lines; modules ≤ 600 lines; a milestone past 1.5 × its line estimate stops for a re-plan ADR; a core change forced by any consumer, including a new app such as the owner's planned later apps, after the schema freeze (end of M2) is recorded as a generality failure.

## Alternatives

Fake-centred tests (rejected). Owner-machine integration lane (rejected). A stateless fixture as the M1 walking skeleton (rejected: the predecessor's lesson was a real consumer on a real host in the first milestone; `fx-web` stays a CI fixture).

## Consequences

CI minutes per push are about 45 (three lanes of under 15 minutes each), free on GitHub-hosted runners, arm64 runners included, because the repository is public (owner decision OD-3; spike S13 confirms the arm64 runner in M0). arm64 is claimed only for the combinations its lane passes ([ADR-0025](0025-host-baseline.md)).
