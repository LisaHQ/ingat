# ADR-0026 App images are built in each app's CI and pulled, never built on the host

**Status:** Accepted (owner decision OD-11, option (b), 2026-10-15).

**In plain words:** Ingat never builds app images. Each app's CI builds and publishes them; Ingat pulls them, pins them by ID and digest, and accepts an image the app builds itself only when its labels name the exact commit being installed.

## Context

Owner decision OD-11 asked where app images are built: (a) on the host in `prepare` with a buildx bundled in the tool image, or (b) in each app's CI, published to a registry and pulled by the host. Both reference consumers' repositories are public, so images published to GHCR are free to store and pull anonymously. An on-host build loads the host beside its live instances and drills, fills the Docker root with build cache, rebuilds the same commit into different image IDs on another host, and was the largest unverified item of M1-M2 (spike S4's build checks). The design left "the key that names the source" to this ADR ([ROADMAP.md](../ROADMAP.md) M0, [MANIFEST_SPEC.md](../../app-developers/MANIFEST_SPEC.md) §2.1).

## Decision

- Ingat never builds images. The tool image carries no buildx, and `prepare` runs no build.
- No new manifest key. The image reference a Compose service names, rendered with the instance's params for the candidate (for example a `template` param `"ghcr.io/<owner>/<app>:{commit}"`), is the source. `prepare` pulls every image of the candidate once by that reference (a reference by digest that is already present is not pulled again), then pins it by image ID and records its repository digest in the candidate and the image ledger.
- `[compose] build_services` keeps its meaning: the services whose images the app itself produces. For them `expect_labels` is required and at least one of its values must contain `{commit}` (normally `org.opencontainers.image.revision = "{commit}"`), so a pulled image is accepted only when its labels bind it to the exact commit being deployed. A mismatch refuses the candidate; a tag is never trusted alone.
- `[compose] build_files` and `build_env` stay in schema 1 but are unused until on-host builds return (the deferred item in [ROADMAP.md](../ROADMAP.md) §4).
- Each app's CI publishes images for the architecture of every host it runs on, tagged by commit and labelled with the OCI `version` and `revision` (a consumer-side change).

## Alternatives

(a) Build on the host with buildx through Compose's Bake (rejected: host load and build cache beside production, the spike's largest unverified item, and image IDs that differ between hosts, which makes cross-host restore run rebuilt bytes). A new manifest key naming a registry repository per service (rejected: the Compose file already names the image; a second name could disagree with it). Pulling by a digest recorded in the app repository (rejected: a commit cannot record the digest of an image built from itself).

## Consequences

The host never builds, so spike S4 drops its build checks and S15 its on-host build stage. A bundle's recorded images can be pulled by digest on any host, so a cross-host restore (M4) runs the exact bytes. An app without CI image publishing waits for the deferred on-host build path. Tests use a local registry inside the scratch Docker daemon for the `build_services` path.
