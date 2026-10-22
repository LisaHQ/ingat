# ADR-0018 App environment control and holds

**Status:** Accepted.

**In plain words:** An app declares every setting it accepts. Some may only change with the strongest approval, some are forbidden, and some Ingat fills in itself. Isolated runs (test restores, and the staging step of a real restore) get holds: settings that stop them from sending real mail and let them start without outside access.

## Context

The SQLite consumer's real outbound mail sending requires an owner-only enabling variable; its image fixes its database and data-directory paths; restoring older data into a live topology can repeat outbound mail.

## Decision

`[app_env]` keys declare `required`, `allowed`, `pattern`, `secret`, `owner_gated`, `tool_managed`, and the manifest lists `forbidden` keys. Owner-gated changes are class D. Isolated runs apply `[holds]`, drop owner-gated and secret keys, and use internal networks. Holds also carry values a service needs to start without a default route (the PostgreSQL consumer's web service needs its trusted-proxy address set; `fx-pg` mirrors it). Apps with outbound side effects restore only through their own restore task and end `held`.

## Alternatives

Free-form env files (rejected: no gating, data redirection possible).

## Consequences

The SQLite consumer's env file becomes an Ingat-rendered file; the owner edits values in `instance.toml` and secrets with `ingat secret set`.
