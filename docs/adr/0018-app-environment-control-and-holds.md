# ADR-0018 App environment control and holds

**Status:** Accepted.

## Context

The SQLite consumer's real outbound mail sending requires an owner-only enabling variable; its image fixes its database and data-directory paths; restoring older data into a live topology can repeat outbound mail.

## Decision

`[app_env]` keys declare `required`, `allowed`, `pattern`, `secret`, `owner_gated`, `tool_managed`, and the manifest lists `forbidden` keys. Owner-gated changes are class D. Isolated runs apply `[holds]`, drop owner-gated and secret keys, and use internal networks. Holds also carry values a service needs to start without a default route (the PostgreSQL consumer's web service needs its trusted-proxy address set; `fx-pg` mirrors it). Apps with outbound side effects restore only through their own restore task and end `held`.

## Alternatives

Free-form env files (rejected: no gating, data redirection possible).

## Consequences

The SQLite consumer's env file becomes an Ingat-rendered file; the owner edits values in `instance.toml` and secrets with `ingat secret set`.
