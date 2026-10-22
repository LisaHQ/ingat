# ADR-0006 Compose runs on the app's own files plus a generated override

**English** · [Tiếng Việt](0006-compose-app-files-plus-override.vi.md)

**Status:** Accepted.

**In plain words:** Ingat runs Docker Compose on the app's own, unchanged Compose files plus one file it generates. That file pins exact images and adds labels that never change between deployments, so only services whose settings really changed are recreated.

## Context

Executing from a re-rendered `compose config` model risks escape drift across Compose versions: the PostgreSQL consumer's healthcheck uses `$$POSTGRES_USER`, and the predecessor needed escape calibration. Shell variables override `--env-file`.

## Decision

Every call is `docker compose -p <project> --project-directory <export> -f <app files> -f <override.yaml> --env-file <rendered> <verb> <explicit services>` with an empty environment; `up` always has `--no-build --pull never`; tasks are `run --rm --no-deps -T --name … --label …`. The override is generated from data (JSON-quoted scalars plus `!reset`); it also gives every service without its own `logging` the `local` driver with rotation, and the service of a terminal task the `none` driver ([ADR-0025](0025-host-baseline.md)). The merged model from `config --format json --no-env-resolution` is used only for the policy check and the fingerprint ([ARCHITECTURE.md](../ARCHITECTURE.md) §6).

## Alternatives

Execute from the transformed model (rejected: the drift above; unverified fidelity). Hand-written override grammar (rejected: the predecessor's round-trip grammar).

## Consequences

App Compose files stay unmodified. Compose features the override relies on (`!reset`, `external` volume names, `image: sha256:` pins, `--no-env-resolution`) are spike S4-S5 items. Because labels enter Compose's per-service config hash, the override adds only stable identity labels (`instance`, `role`); the deployment sequence lives only in deployment records, and the rendered env file is content-addressed, so a service is recreated only when its effective configuration changes ([ARCHITECTURE.md](../ARCHITECTURE.md) §6.2).
