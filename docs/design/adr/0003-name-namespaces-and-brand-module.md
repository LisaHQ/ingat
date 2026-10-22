# ADR-0003 Name, namespaces and one brand module

**Status:** Accepted; account, namespace and visibility decided by the owner on 2026-10-14 (owner decisions OD-2, OD-3); the product name Ingat confirmed by the owner on 2026-10-14 (owner decision OD-1); default roots made generic the same day, before any implementation ([ADR-0025](0025-host-baseline.md)).

**In plain words:** The names are fixed once: Ingat, the `ingat` command, the LisaHQ organisation, the label and image names, and the default folders. In code they live only in one names file and the start-script template, because Docker labels cannot be renamed later.

## Context

Docker labels on volumes and networks cannot change after creation; the predecessor wrote identifiers before its naming decision. Docker asks third-party tools to prefix label keys with a reverse-DNS name they control and reserves `com.docker.*`, `io.docker.*` and `org.dockerproject.*` ([Docker object labels](https://docs.docker.com/engine/manage-resources/labels/)). The owner chose the GitHub organization LisaHQ and a public repository.

## Decision

Product Ingat, CLI `ingat`, repository `github.com/LisaHQ/ingat`, environment prefix `INGAT_`, label namespace `io.github.lisahq.ingat.` (lowercase), image `ghcr.io/lisahq/ingat`, default roots `/srv/ingat` and `/srv/ingat-backups` (configurable at install; a platform profile passes its own, for example `/volume1/ingat` and `/volume1/ingat-backups` on DSM, as install values rather than code defaults: [ADR-0025](0025-host-baseline.md)). All of them live only in `src/ingat/brand.py` and the wrapper template; a lint test forbids the literals elsewhere in code. Docs use them literally.

## Alternatives

Lodge, Ghim, Upkip (owner decision OD-1). Kipu, the fallback of an earlier naming audit: the audit gave it no intended meaning and proposed it as the cleanest brand by collision checks for an owner who wanted a brand rather than a descriptive name, noting Finnish "pain" only as an adjacent risk. Not chosen: it carries no meaning for this tool, and Ingat checks as clean while meaning "take care".

## Consequences

Every form follows the name (`github.com/LisaHQ/ingat`, `io.github.lisahq.ingat.`, `ghcr.io/lisahq/ingat`). A rename before M1's first real instance would still be a search-and-replace plus one constants file. After real volumes exist, renaming means new instances plus restores.
