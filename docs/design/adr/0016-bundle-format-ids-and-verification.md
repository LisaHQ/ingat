# ADR-0016 Bundle format, ids and verification levels

**English** · [Tiếng Việt](0016-bundle-format-ids-and-verification.vi.md)

**Status:** Accepted.

**In plain words:** A backup copy (bundle) is a folder with a checksum file that lists every file; its fingerprint is the hash of that checksum file, recorded in a list only root can open, so any change is caught. Its id, its name, follows the app's own naming pattern. Two check levels, "verified" and "restore-tested", are recorded outside the bundle.

## Context

The PostgreSQL consumer's backup tooling accepts only backup names matching `<YYYYMMDDTHHMMSSZ>-daily|manual|pre-release-<label>` and a not-before time in `YYYY-MM-DDTHH:MM:SSZ`. Verification inside the sealed bundle would make its hash circular.

## Decision

A bundle is a directory (`bundle.json`, `SHA256SUMS`, `payload/<entry>/`, `meta/`); its hash is SHA-256 of `SHA256SUMS`, recorded in a root-only catalog. Ids come from per-class naming templates in the manifest (an app maps them to its own grammar). Two levels, `verified` and `restore-tested`, kept outside the bundle ([LIFECYCLE.md](../LIFECYCLE.md) §5.3-5.5). `{freeze_at}` renders exactly in that consumer's UTC grammar; a conformance test runs it against the consumer's real migrate command (M3).

## Alternatives

Tar bundles (rejected: no consumer needs them; the predecessor's two-pass tar import returns only if one does). A tool-owned id unrelated to the app grammar (rejected: breaks the PostgreSQL consumer's backups).

## Consequences

Both consumers' own verifiers keep working on Ingat's bundles. Bundles never hold secrets or the resolved model.
