# ADR-0004 Runtime: Python 3.13 inside a pinned image, run by a POSIX wrapper

**Status:** Accepted (the M0 spike can trigger the fallback); revised 2026-10-14, before any implementation, for platform-neutral host support: the image is multi-arch ([ADR-0025](0025-host-baseline.md)).

**In plain words:** Ingat ships as one container image, for `x86_64` and `arm64`, with a fixed Python, Docker command line, Compose and git inside. A tiny shell script on the machine starts it, so every machine runs exactly the files that were tested, whatever Python or Compose the machine has itself.

## Context

Ingat runs on any Linux Docker host, and host Python and host Compose differ by platform. DSM's Python is end of life (3.8 system, 3.9 package). Container Manager 24.0.2-1706, the newest build (it needs DSM 7.4), ships Synology's build of Engine 24.0.2 (API 1.43); a later build may change the Engine, which the version gate and re-certification handle ([ADR-0014](0014-tiered-version-gate.md)). Synology does not publish the bundled Compose version. A Linux host with Docker's packages runs Engine 29.x. Hosts may be `amd64` or `arm64`. The predecessor's host-Python trust machinery cost about 4.9k lines and froze upgrades. The owner reviews Python.

## Decision

One multi-arch OCI image per release (`linux/amd64` and `linux/arm64` under one index digest; arm64 is claimed only after its CI lane passes: [ADR-0025](0025-host-baseline.md)) pins Python 3.13, the static docker CLI, Compose v5.x, git and, only if owner decision OD-11 chooses on-host image builds (option a), buildx. A root-owned 20-line `sh` wrapper pins the image digest and runs it with the socket, same-path roots, `--init`, `--network host` and `env -i` ([ARCHITECTURE.md](../ARCHITECTURE.md) §3.3). Standard library first; a dependency needs an ADR and a hash lock.

## Alternatives

Python zipapp on the host interpreter (rejected: end-of-life interpreter, unpinned Compose). Go static binary (rejected as primary: a language the owner does not review, Compose still shipped beside it; the Compose Go SDK needs `docker/cli v28.5.2+incompatible`). Node/TypeScript (rejected: host runtime and large single-executable builds for no gain). **Fallback** if spikes S1-S3 fail: the same package run on the host by a pinned python-build-standalone CPython with the same static binaries under `INGAT_ROOT/runtime/<version>/`, checksum-verified; the code does not change.

## Consequences

CI tests the exact artifact the host runs, per architecture. Every host runs the same bytes for its architecture. Upgrades are image swaps. Socket access is root-equivalent, as for any option.
