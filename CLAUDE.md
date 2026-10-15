# Ingat AI Instruction

This file is the canonical AI instruction entry point for the Ingat repository. If any repository instruction conflicts with this file, this file takes precedence unless the owner explicitly overrides it in the current task.

## 1. Operating Contract

- Communicate with the owner in Vietnamese unless explicitly requested otherwise.
- Use English for code, comments, identifiers, file names, commit messages and technical documentation. Operator runbooks get a Vietnamese mirror under `docs/runbooks/vi/`; English is canonical.
- Be direct, practical and host-aware. Explain tradeoffs only when they affect data safety, correctness, recoverability or the owner's intent.
- State a concise plan before large, destructive, security-sensitive or non-trivial changes.
- Ask only when a missing decision blocks correct or safe progress; otherwise make the safest minimal assumption and say so.
- After editing, summarize changed files concisely.
- NEVER claim a command, build, test, CI run, host check or release succeeded unless it actually ran and completed successfully.

## 2. Prime Directive

> **Do not reach a conclusion until it can be justified as the best available conclusion under the known constraints, evidence and project context.**

Before designing, reviewing or implementing: understand what is required; verify material assumptions against the current docs, code, tests and CI evidence; consider a meaningful alternative when one exists; challenge the answer for wrong assumptions, missed constraints and needless complexity; stop investigating when the evidence is sufficient.

Make the smallest complete change. Never over-engineer, broaden scope, or add a concept, dependency, step type, task mode, probe kind, template variable or manifest key without an ADR and a named consumer need. Keep implemented behaviour, planned capability and proposed design explicitly separate.

## 3. Read Only the Context the Task Needs

Search headings first and read only the sections the decision needs:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — scope, runtime, execution model, modules, layout, security, testing, hosts.
- [`docs/LIFECYCLE.md`](docs/LIFECYCLE.md) — safety floors F1-F17, approval classes, state machines, operations, data, exit codes.
- [`docs/MANIFEST_SPEC.md`](docs/MANIFEST_SPEC.md) — `ingat.toml` and `instance.toml` schemas and the generic examples (consumer manifests live in their own app repositories: OD-3).
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — the current milestone, its slices and exit gate. Read only the current and directly relevant milestones.
- [`docs/adr/`](docs/adr/README.md) — accepted decisions, one file per ADR (`docs/adr/NNNN-<slug>.md`), indexed in `docs/adr/README.md`. A change to an accepted decision is a new ADR.
- [`README.md`](README.md) — current status, features, conventions (status tags, generic consumer aliases), names and the host support summary (`docs/ARCHITECTURE.md` §11); install and commands from M1.

This repository is public and holds generic content only (OD-3, decided). Consumer-specific notes and the owner's decision record are kept outside it; never recreate them here.

**Private notes.** The owner's private notes (consumer notes, the owner decision record, platform research and the original design package) live in the `_private/` folder of the working copy, which `.gitignore` excludes. Development agents may read them for context. Never track them (no `git add -f`), never copy their content into a tracked file, never quote them, and never link to them from a tracked file. When a design point depends on them, write the generic reason or cite the owner decision id ("owner decision OD-n").

Source authority for intended behaviour: (1) the safety floors in `LIFECYCLE.md` §1, (2) accepted ADRs, (3) `ARCHITECTURE.md`, `LIFECYCLE.md`, `MANIFEST_SPEC.md`, (4) `ROADMAP.md` for order and scope. Code, tests and CI evidence are authoritative for what exists now but never silently override a floor. If docs and code conflict, expose the conflict.

## 4. Project Identity and Non-Negotiable Invariants

Ingat deploys, updates, backs up, verifies, restores, adopts and retires Docker Compose applications on one host: any machine with a local Linux Docker Engine (24.0 or later) and Compose v2, on any distribution or appliance (bare-metal server, VM, VPS, a NAS that offers Docker, a small board). Platform differences are detected capabilities and per-platform certification, never a branch on a platform name, vendor or model (`docs/ARCHITECTURE.md` §11). It is NOT a PaaS, orchestrator, scheduler, backup transport, reverse proxy, web UI or database tool. It has no compatibility with the earlier in-house deployment controller it replaces.

Priority order: 1. Data safety and correctness, 2. Reliability and recoverability, 3. Maintainability, 4. Architecture integrity, 5. Host fit (any Linux Docker host; certified platform profiles), 6. Operator and agent usability, 7. Performance, 8. Developer convenience.

Never weaken a safety floor. In short:

- One explicit instance per command; the name is the Compose project; engine ID bound.
- Plan before effect; a refused, stale or read-only command leaves no trace.
- Approval binds a plan hash and fingerprint; class D needs a real terminal and a challenge, and `apply` never covers it.
- Intent before effect, observe before retry; one open operation per instance; `unknown` is never retried blind.
- Preserve before replace: writers stopped, sealed and verified pre-change bundle, then change.
- Never overwrite data: new generation, pointer switch, old generation kept.
- Delete only owned, listed, re-proved objects; never `prune`, never `down -v`. A foreign object is never touched: not stopped, started, exec'd into, mounted, relabelled, restored into or deleted; adoption starts from a payload of the app's own backup command that the owner produced.
- Only Ingat writes `verified` and `restore-tested`, bound to a bundle hash.
- Secrets live only in files; never in argv, records, bundles, logs or errors; terminal output is never captured and never written by a logging driver.
- Isolated runs use internal networks, no ports and holds, and never touch live data.
- Mutating commands run only on tested platforms (`tested.json`, generated by CI) and only with a host certification of the host's platform build, on every host.
- Task containers are named per attempt, labelled, stopped before the lock is released; an exited one is evidence, never a blocker; mutating `exec` only in isolated projects.
- Live services carry only stable identity labels, so a deploy recreates only services whose configuration changed.
- Data stores are ready only after their stable readiness probe.
- No `--force`, no `--yes`, no policy file that disables a floor.

## 5. Architecture Rules

- Layers: `cli → ops → core → (model, policy) and (adapters, store)`; the import-direction test is authoritative.
- Only `adapters/runner.py` imports `subprocess`. Mutating Docker/Compose calls require an `EffectToken` that only the executor issues inside an open, journaled step.
- No app or engine knowledge in the core. Forbidden literals in `src/`: `postgres`, `pg_`, `sqlite`, `alembic`, `backend`, `frontend`, `uvicorn`, `node`, and any consumer app name (the CI lint reads those names from a CI secret, so the list itself is never committed; the content rule below keeps consumer names out of the whole repository). Fixtures and tests may name engines.
- **Content rule (OD-3).** This repository is public and generic: no consumer names or identifiers, consumer manifests, environment variables, commands, role or table names, change ids, file paths, instance names or notes, and no citations into private material. Consumers appear only through the aliases defined in `README.md`: "the PostgreSQL consumer" (fixture `fx-pg`), "the SQLite consumer" (fixture `fx-lite`) and the stateless fixture `fx-web`; example instance names are `pg-staging`, `pg-prod`, `lite-test` and `site`. The predecessor is "an earlier in-house deployment controller"; a lesson from it is a short generic reason, never a citation or a defect id. Host-specific values (hostnames, real ports, subnets, URLs, user names, emails, paths of real instances or of the owner's machines, secrets, deploy keys) never enter any repository; they live only in `instance.toml` and secret files on the host and in the owner's offline encrypted copy. An app's `ingat.toml` in its own (public) repository is generic too. Host certifications and platform facts name only the platform software and architecture (OS or appliance release and build such as the DSM build, the Engine package build such as the Container Manager build, the Engine version, Git commit and build time, containerd and runc versions, kernel, architecture such as `x86_64` or `aarch64`), never a device model (NAS, server or board), a CPU model or details of the owner's units (RAM, volume layout, hostnames, other devices or how they are used); the docs describe hosts generically by minimum Engine and platform versions and minimum hardware (`docs/ARCHITECTURE.md` §11.4).
- **Generality rule.** A new app must fit without a core change, and a new host platform without a platform branch: app and host differences are detected capabilities plus a certification per platform build, never branches on a platform name, vendor, model or an app name (`docs/ARCHITECTURE.md` §11.3). A gap is an ADR and a recorded generality failure.
- Product name, CLI name, label namespace, environment prefix and default roots appear only in `src/ingat/brand.py` and the wrapper template.
- Compose always runs on the app's own files plus the generated override, with an explicit service list, `--no-build --pull never`, an empty environment and a rendered env file. Never execute from a re-rendered model.
- Every module stays at or under 600 lines. Records carry explicit types; never derive behaviour from resource-name prefixes. Never call `sync(2)`; fsync exactly what is published.
- Standard library first. A third-party dependency needs an ADR and a hash lock.

## 6. Change, Error and Security Discipline

- Preserve established style and patterns; never mix unrelated refactors with requested work.
- Update directly affected references, tests and docs only. Never create parallel doc structures.
- Never silently ignore a failure or use a broad catch without a defined recovery path; preserve original exceptions; user-facing errors name keys and positions, never secret values or hashes.
- For state-changing code, account for interruption at every step boundary, duplicate input, retries and recovery; extend the generated crash matrix when you add a step.
- **Host safety for development agents.** This file governs agents developing Ingat in this repository. They never run any Ingat command, `docker` command or `install.sh` against any of the owner's hosts; they use CI and scratch dind daemons only. Never open real `instance.toml` files, secret files, `.env` files or deploy keys; tests use generated test values only. Operations agents that run Ingat on a host in the owner's session follow the owner's operations rules (owner decision OD-10, recorded in the owner's private notes: class A and B, class C only with an owner-given plan hash, never class D, enforced by their own tool deny rules), not this file.
- Never weaken the policy deny-list, the version gate or an approval class to make a test or a consumer pass; record a generality gap in an ADR instead.

## 7. Testing and Validation

- Verify commands against `pyproject.toml`, the CI workflow and `README.md` before treating them as canonical.
- Real Docker is the gate: CI runs `docker:24.0.2-dind` and the one exact `docker:29.Y.Z-dind` tag pinned in `image/versions.lock` on `amd64`, plus an arm64 lane (the 29.Y.Z tag on GitHub-hosted arm64 runners), with the exact multi-arch tool image built in that pipeline; arm64 is claimed only after its lane passes. Upstream dind is the evidence for support tier 1 (upstream Engine on Linux); it is not a vendor-built engine, so only a host certification covers a support-tier-2 platform such as Synology's Container Manager. Run the narrowest relevant suite first, then broader suites proportional to risk.
- Tests assert behaviour through the CLI and observable effects (files, Docker inventory, Docker events, exit codes, JSON). Never test source text or internal names.
- Required suites for a change that touches operations: no-trace, crash matrix, session loss, secret canary; add readiness, isolation, recreate-scope and generation-safety tests when the change touches data paths or the override, and the upgrade suite when it touches any persisted record (record changes are additive and optional within a `state_schema`: ADR-0023).
- Tests use isolated scratch roots and dind daemons; they never touch a real host or real data.
- One verdict vocabulary: `PASS`, `FAIL`, `BLOCKED`. Evidence is a CI run at a commit SHA or a committed host certification. Never hand-edit `tested.json` or write a pass claim without a log.

## 8. Version Control Summary

After file changes, every response includes a concise `Commit description`. Leave changes uncommitted by default; never create or modify a commit unless the owner explicitly asks.

Commit description:

```text
Describe the overall completed change directly without a type or scope prefix.

- type(scope): Describe the first logical change.
- type(scope): Describe each additional logical change when applicable.
```

The first line is plain imperative text without a Conventional Commits prefix; each bullet uses the most specific prefix (`feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `perf`, `revert`) with an optional scope; the whole description is one fenced `text` block.

## 9. Releases

- Semantic versions, tags `vX.Y.Z`. A release publishes the multi-arch image `ghcr.io/lisahq/ingat` (`linux/amd64` and `linux/arm64`) by index digest, `SHA256SUMS` (version → image digest and tarball hashes), optional per-architecture `docker save` tarballs, an SBOM and the CI-generated `tested.json`.
- A docker CLI, Compose or buildx bump is always its own release with CI evidence.
- Release notes state the source SHA, the support matrix (tested combinations only), state-schema changes and migration steps, known limitations, and validation status; unknown checks are marked pending, never passed.
- Preparing release information is read-only: never tag, publish or deploy unless the owner explicitly asks.
