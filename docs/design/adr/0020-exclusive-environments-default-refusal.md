# ADR-0020 Exclusive environments default to refusal

**English** · [Tiếng Việt](0020-exclusive-environments-default-refusal.vi.md)

**Status:** Accepted, pending owner decision OD-5.

**In plain words:** An app can say that its production copy must not share a machine with another copy of the same app. Ingat then refuses by default. The owner may relax the rule later (OD-5).

## Context

The PostgreSQL consumer's own deployment rules forbid a staging instance on the Docker daemon that runs its production, and its release script refuses while a staging project exists. The `safety` proposal dropped the rule silently (Lens A must-fix). A host running two PostgreSQL instances also needs RAM.

## Decision

The manifest key `exclusive_environments = ["production"]` keeps the rule: a production instance refuses to deploy or start while another instance of the same app is registered on the host, and vice versa for `init`. The owner may change the rule in the consumer's manifest after OD-5; if the owner relaxes it before the M2 schema freeze, the key leaves schema 1 (it then has no consumer) and the rule stays owner practice plus the `[drill] min_free_memory` check.

## Alternatives

Drop the rule because Ingat separates projects, volumes, secrets and backups (the `safety`/`container` position). Keep it only as owner practice from the start (the review's suggestion, rejected as the default: it would undo a Lens A must-fix, default refusal, before the owner has decided OD-5).

## Consequences

With the default, the staging instance (`pg-staging`) must be purged (M3) or moved to another host before the production instance (`pg-prod`) starts on its host.
