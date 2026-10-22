# ADR-0009 The app manifest lives in the app repository; TOML; closed vocabularies

**Status:** Accepted.

**In plain words:** Each app describes itself in `ingat.toml` in its own repository, read from the exact version being installed. The format is TOML, and every list of allowed words in it (steps, task modes, checks, placeholders) is fixed: a new word needs an ADR and a real app that needs it.

## Context

The predecessor's installed control-plane profile drifted from app releases and could not describe a second app. Both consumers already ship their operations in their images.

## Decision

`ingat.toml` at the app repository root, read from the deployed commit and snapshotted per deployment; `instance.toml` on the host holds values only and is never rewritten by Ingat. TOML parsed strictly with `tomllib`. Closed sets: step types, task modes (`run`, `exec`), probe kinds (`health`, `exec`, `http`), template variables. A new form needs an ADR and a named consumer ([MANIFEST_SPEC.md](../../app-developers/MANIFEST_SPEC.md)).

## Alternatives

YAML (rejected: implicit typing). A manifest stored on the host (rejected: topology skew on rollback). An expression language (rejected: the risk of growing a mini-language).

## Consequences

Rollback uses the matching topology automatically. `ingat validate` runs in each app's CI from M1.
