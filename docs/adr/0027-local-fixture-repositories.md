# ADR-0027 Local fixture repositories for selftest and tests

**Status:** Accepted (2026-10-15).

## Context

`selftest --host` (the first item of the M1 exit gate) and the CI suites run the lifecycle loop on the fixtures `fx-lite` and `fx-web` through the same git source path a real app uses ([ARCHITECTURE.md](../ARCHITECTURE.md) §10.4). The instance schema allows only `ssh` and `https` repository URLs, and the git adapter allows only those protocols, so a fixture would need a git server on every host that runs `selftest`, with its own keys.

## Decision

An instance `[source] repo` may also be a `file://` URL whose path lies under `<INGAT_ROOT>/cache/fixtures/`. Only `selftest` creates repositories there (from the fixture trees shipped in the tool image), and tests create them in their scratch roots the same way. The git adapter allows the `file` protocol only for such a URL; every other `file://` URL, and any other protocol, stays refused. `INGAT_ROOT` is `root:root 0700`, so only root can place a repository there.

## Alternatives

An SSH git server container for selftest and CI (rejected: selftest on a host must not depend on a server, a key pair or a listener). Image-sourced fixtures (rejected: image sources arrive in M2, and selftest must exercise the git path the first real consumer uses).

## Consequences

Selftest and the suites exercise fetch, ref resolution, the manifest read and the export exactly as for a real app. The extra protocol cannot reach outside the tool root.
