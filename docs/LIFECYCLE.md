# Ingat lifecycle: operations, state machines, safety floors, data

Status: **Decided** unless tagged **Planned Mx** or **Open OD-n** (an open owner decision). The M1 operations exist in code; they have run only on local scratch Docker daemons, not yet in CI or on a host ([README](../README.md#status)). Manifest keys referenced here are defined in [MANIFEST_SPEC.md](MANIFEST_SPEC.md); processes, layout and the Compose contract are in [ARCHITECTURE.md](ARCHITECTURE.md).

Examples name two reference consumers by alias: *the PostgreSQL consumer* (PostgreSQL, backend and web services; an explicit migrate step; role grants after restore; an invariant-check command), mirrored by fixture `fx-pg`, and *the SQLite consumer* (one container; SQLite in a bind-mounted data directory; online app-native backup; an outbound mail queue; migrate at start), mirrored by fixture `fx-lite`. `fx-web` is the stateless fixture ([ARCHITECTURE.md](ARCHITECTURE.md) §10.2).

## 1. Safety floors

Floors are code. No flag, manifest key, instance key or environment variable disables one, and there is no `--force` or `--yes`.

| ID | Floor | Enforced by |
|---|---|---|
| F1 | **One explicit instance.** Every instance command names exactly one instance, resolved once and passed down unchanged; there is no default instance. The instance name is the Compose project. The daemon's engine ID must equal `host.json`. | CLI table, executor |
| F2 | **Plan before effect; a refusal leaves no trace.** All checks run in a pure plan phase. A refused, stale or cancelled-before-effect command leaves `instances/` and the labelled Docker inventory identical (caches named in [ARCHITECTURE.md](ARCHITECTURE.md) §5.3 and the lock holder files `lock.holder.json` and `host.lock.holder.json` excepted; a refusal inside a started executor also leaves its approved plan in `plans/` and its run file in `host/runs/`). | plan framework, no-trace suite |
| F3 | **Approval binds a plan.** Class C and D operations run only after approval of a plan whose hash covers inputs and the observed fingerprint (deployment seq, container IDs and config hashes, generation pointers, bundle hashes, open op). The executor re-observes and refuses a stale plan. | `core/approval.py`, executor |
| F4 | **Frozen inputs.** An operation executes only its exported commit, manifest bytes, image IDs, generated override and rendered env files recorded in the plan. | executor |
| F5 | **Intent before effect; observe before retry.** At most one open operation per instance; it blocks every other mutation except `resume`, `abandon`, `cancel` and tasks the open step allows. An `unknown` outcome is never retried blind. | journal, executor |
| F6 | **Preserve before replace.** A deploy that changes the image of any writer or data service stops the writers, captures a pre-change bundle with the current release, seals and verifies it, and only then migrates or starts the new image. If preservation fails, nothing is replaced. | deploy planner |
| F7 | **Never overwrite data.** Restore, data rollback and data-image moves fill a new generation and switch a pointer; the previous generation stays until an explicit class D prune, which never removes the current or the previous generation. | generations, override |
| F8 | **Closed, ownership-proved deletion.** Ingat deletes only objects that carry its labels and appear in a frozen deletion plan; each item is re-proved (ID, creation time, labels, users) right before removal. Never `prune`, never `down -v`, never a bind path other than a listed generation Ingat created. Until M3 Ingat removes no images. A foreign object is never touched: Ingat never stops, starts, execs into, mounts, relabels, restores into or deletes one; adoption (M4) starts from a payload the owner produced with the app's own backup command (§4.16). | delete step, policy |
| F9 | **Diagnostics never write.** `status`, `doctor`, `list`, `ps`, `logs`, `bundles`, `history`, `validate`, `plan` write nothing except `plans/` for `plan`. | CLI table, no-trace suite |
| F10 | **Evidence-bound verification.** Only Ingat writes `verified` and `restore-tested`, each bound to a bundle hash. Purge needs a restore-tested final bundle unless the instance was created `disposable`. | verify, purge |
| F11 | **Provenance survives.** Deployment records keep tag, commit, image IDs, manifest and model hashes and schema; images of the current and previous deployment and of pinned pre-change bundles are kept. | records, image ledger |
| F12 | **Secrets stay in files.** Never in argv, plans, records, bundles, logs or errors; captured output is redacted; `terminal` output is never captured. | runner, `Secret` type |
| F13 | **Isolation and holds.** Isolated runs (drills, restore staging) use internal networks, no published ports, pool subnets and the manifest's holds, and never touch the live project or the live generation. Apps with outbound side effects restore only through their own restore task; one live instance per lineage (check Planned M4). | override, planners |
| F14 | **Tested platform only.** Version-gate tiers ([ARCHITECTURE.md](ARCHITECTURE.md) §3.6); no override. | `policy/gate.py` |
| F15 | **Task containers are owned processes.** Every one-off task container has a deterministic per-attempt name and op labels, is stopped and awaited before the lock is released, and blocks `resume`/`abandon` while alive; an exited one left by a crash is recorded as evidence for its step and removed ([ARCHITECTURE.md](ARCHITECTURE.md) §4.5). Mutating `exec` steps run only inside isolated projects. | executor, validation |
| F16 | **Data stores are ready only when proven.** Every start of a data service waits for its store's stable readiness probe before any task, restore or install step touches it. | `Up` step |
| F17 | **No weakening switch.** No `--force`, no `--yes`, no policy file; the only escape from a floor is a different, explicitly approved operation. | design rule |

## 2. Approval classes and commands

| Class | Meaning | Approval | Unattended |
|---|---|---|---|
| A | read-only | none | yes |
| B | non-destructive: writes only new artifacts (bundles, verification records, candidates) or removes only what retention allows | none | yes |
| C | changing | on a terminal, type the instance name; otherwise `ingat apply <≥12 hex of plan hash>` for a plan produced by `ingat plan …` and handed over by the owner | only through `apply` |
| D | destructive or data-losing | on a **real terminal only**: type the phrase plus a random 4-character challenge (for example `PURGE pg-staging k7q2`). `apply` is never accepted for class D, `disposable` instances included. | no |

`selftest` and `conformance` drive their own throwaway instances inside one command and delete only objects that command created; they never use `apply`, and the plans they run inside the command need no approval of their own (no typed name, no class D challenge).

| Command | Class | Runs in | Milestone |
|---|---|---|---|
| `version`, `host check`, `status [<i>] [--json]`, `doctor <i>`, `list`, `ps <i>`, `logs <i> <service> [--since]`, `history <i>`, `validate <repo-dir>`, `attach <i>`, `bundles <i>` | A | CLI | M1 |
| `plan <command…>` | A | CLI | M2 |
| `prepare <i> <ref>` | B | executor | M1 |
| `prepare <i> --image <svc>=<repo>@sha256:…` | B | executor | M2 |
| `task <i> <name>` where the task's effect is `read` | B | executor | M1 |
| `cancel <i>` | B | CLI (writes the cancel file only) | M1 |
| `selftest [--host]` | B | host executor (`selftest --offline`: CLI, no daemon) | M1 |
| `backup <i> [--class <class>] [--reason TEXT] [--prune]`, `verify <i> <bundle>\|--latest`, `verify … --restore-test`, `prune <i> --bundles [--apply]`, `scheduled backup\|verify\|task <i> …`, `scheduled status` | B | executor (`scheduled status`: CLI, writes only `host/attention.json`) | M1 |
| `host init` | C | CLI (host lock; no Docker change) | M1 |
| `init <i> --config <file> --ref <ref>` | C | CLI (host lock; no Docker change) | M1 |
| `start\|stop\|restart <i> [<service>…]`, `resume <i>`, `abandon <i>` | C | executor | M1 |
| `apply <hash>` | C | executor | M2 |
| `deploy <i> <ref>` (first install, update, config-only) | C, or D when the plan changes an owner-gated key or a data-service image | executor | M1 stateless and bind-store apps (an owner-gated change is refused until M2), M2 volume stores, data services and image sources, data-image change M3 |
| `task <i> <name>` with effect `app-write` or `data` | C | executor, or CLI for terminal tasks | M1 |
| `secret set <i> <KEY>` (value from stdin) | C | CLI (instance lock; no Docker change) | M2 |
| `restore <i> --bundle <id> --reason TEXT` into an instance that was never deployed | C | executor | M2 |
| `restore <i> --bundle <id> --reason TEXT` into an instance with data; `start <i> --unfreeze` | D | executor | M2 |
| `rollback <i> [--to <seq>] [--accept-schema <rev>]` | C when code-only; D when it restores data, when writes reopened since the target, or with `--accept-schema` | executor | M3 |
| `restore <i> --generation <store>=g<N>`, `prune <i> --generations\|--images [--apply]`, `purge <i>`, `resolve <i> --step N --as done\|not-done --reason TEXT` | D | executor | M3 |
| `check [<i>]`, `schedule render <i> --systemd\|--cron\|--dsm`, `conformance --repo <dir> [--from <ref>]` | A/B | CLI/executor | M3 |
| `import <dir> --into <i>`, `export-config <i> --to <dir>`, `host rebind` (D) | B/C/D | executor | M4 |
| `import --payload <dir> --into <i> --release <ref> --from <name> [--id <bundle-id>] --reason TEXT` (adoption, §4.16) | B | executor | M4 |
| `self-upgrade <version>`, `self-rollback`, `state migrate` | C | host executor | M5 |

Operations agents may run class A and B freely and class C only with a plan hash the owner gave them, and never class D. The CLI cannot tell an agent from the owner: an agent that allocates a pty can type a challenge. The rule therefore holds only for agents that obey it; the agent's own tool deny rules enforce it (owner decision OD-10).

## 3. Operation model

### 3.1 Plan, approve, execute

```
parse ─► plan (pure: validate manifest/instance, observe read-only, gate tier, capacity, policy on every model it will run,
         ordered step list, fingerprint, canonical hash)
           │ refusal ─► exit 1 (or 2), nothing written                                             (F2)
           ▼
       approve (class rules) ─► plans/<hash>.json written once
           ▼
       executor: flock ─► open op? ─► orphan check ─► re-observe fingerprint ─► stale ─► refused-stale, exit 1
           ▼
       ops/<seq>-<kind>/ created ─► for each step: intent (fsync) ─► effect (EffectToken) ─► observe ─► done | failed | unknown
           ▼
       close decision journaled (step 0) ─► unwind (failure or abandon) ─► record.json ─► result.json (write-once)
           ─► lock released ─► run file host/runs/<run-id>.json ─► CLI prints outcome and `next`
```

`result.json` exists only for a closed operation, so it is written last: after a crash anywhere in the close, the operation is still open and the next `resume` or `abandon` finishes the close that step 0 recorded, never steps past what the unwind already reversed. Every executor run, a refused one included, leaves a run file (exit, code, message, `next` and warnings); the plan's warnings (a gate tier 1 warning, a skipped retention) are copied into `result.json` and the run file. A plan expires 24 hours after it was made: the executor refuses an expired one (exit 2), and M1 deletes no plan except those of a selftest run's own instances, at its teardown.

### 3.2 Operation states

```
            ┌──────────── refused-stale (exit 1; nothing written under instances/)
planned ─approve─► running ──────────────► completed (exit 0)
                    │  failure before the forward point: undo reversible steps ─► failed-unchanged (exit 3)
                    │     … an undo or teardown that did not complete ─────────────► needs-review   (exit 4)
                    │  failure at/after the forward point: stop writers ──────────► failed-frozen  (exit 3)
                    │  cancel before any effect ────────────────────────────────────► abandoned      (exit 130)
                    │  install pause ──────────────────────────────────────────────► paused         (exit 4) ─resume─► running
                    │  unknown outcome / executor killed / host reboot ─────────────► interrupted    (exit 4)
                    ▼
            interrupted ─resume─► running (rules in §3.4)
            interrupted ─abandon─► abandoned (undo reversible; tear down scratch; writers stay stopped past the forward point)
            interrupted prepare / backup / verify / drill ─next command─► abandoned-auto (recorded undo and teardown), then the new command runs
```

The **forward point** of an operation is the first step after which the previous state cannot be restored by undo: a data-effect task on the live generation (migrate), or the activation step marked `reopens_writes`. In a data-changing update every activation group is forward, because the first start of a candidate writer may already change the data. A `Delete` never counts as the forward point (a failed deletion never stops writers or freezes), nor does the step of a one-step `app-write` task (§3.5), nor a migrate whose first attempt the app `refused` (nothing changed, §4.4). A cancel request after an effect follows the same failure rules with code `cancelled`: `failed-unchanged` before the forward point, `failed-frozen` after it. Every terminal state prints the exact next command; a test asserts that the printed command exists and succeeds from that state, including a restore into a never-deployed instance (an adoption's cut-over) that ends `failed-frozen` (§4.10) (an earlier in-house deployment controller had terminal states with no working way forward).

### 3.3 Step types (closed set; a new type needs an ADR)

| Step | Class | Interruptible | `observe` | Undo |
|---|---|---|---|---|
| `Obtain(services)` (pull, record IDs; Ingat never builds: [ADR-0026](adr/0026-app-images-built-in-app-ci.md)) | scratch | yes | ledger entry with matching ID and labels | none (cache) |
| `RunTask` with effect `read` | scratch | yes | outcome record exists | none |
| `SnapshotLogs(services)` (bounded `docker logs --tail`, redacted, 0600) | scratch | yes | artifact exists | none |
| `Stop(services)` | reversible | no (bounded by `stop_grace_period`) | containers stopped | start them on the recorded deployment |
| `CreateGeneration(store)` | scratch until switched | no | labelled volume or directory plus marker | delete it, only if this op created it and never promoted it |
| `Up(project, services, wait)` | live: reversible before the forward point; isolated: scratch | probes yes | running with the expected image ID and probes stable | stop, then restart the recorded deployment |
| `RunTask` with effect `app-write` or `data` | live: forward (must be `idempotent` or declare `observe`, validation rule); isolated: scratch; a task of `backup.steps` or `backup.verify`: scratch whatever its effect (below) | no (atomic) | per `observe` | none |
| `CaptureBundle(class)` | scratch until sealed; the sealed bundle is kept | yes, until the seal | catalog entry with the bundle hash | discard the partial stage |
| `VerifyBundle` | scratch | yes | verification record for the hash | none |
| `SwitchGeneration(store, from, to)` | reversible until a writer starts on `to` | no | `record.json` pointer | switch back |
| `Teardown(isolated project)` | scratch cleanup | no | own labelled containers and networks gone; it acts only on this operation's own `<i>--t<seq>` or `<i>--r<seq>` (else `not-isolated`), and right before `down` every container and network of the project must carry the instance and op labels (else `foreign`) | none |
| `Delete(plan item)`: a bundle, an owned container ([ARCHITECTURE.md](ARCHITECTURE.md) §7.5) or a selftest generation (below) | forward, but never the forward point (§3.2) | no | item gone; progress saved | none |
| `Record(kind)` | idempotent | no | record written | none |
| `Pause(text, allow_tasks)` | operator | n/a | `resume` called | none |

**Backup tasks are scratch.** Every task listed in `backup.steps` or `backup.verify` is scratch class whatever its declared effect. It may write only into the stage and into the app's own bookkeeping of backups (the SQLite consumer records each backup's outcome in its own database), and validation requires `idempotent = true` for every such task that is not `read`. A backup operation therefore has no forward point: abandoning it never stops or freezes writers, and the retention deletions of a scheduled backup never freeze either.

**Selftest instances.** Two step forms act only on an `ingat-selftest-*` instance whose marker `instances/<i>/selftest.json`, written when selftest creates it, names a selftest run: a `Teardown` of its live project, re-proved like the isolated one (every container and network carries the instance label), and a `Delete` item of kind `generation`, which removes a generation (the current one included) only when its own marker names this instance, store and generation and no container mounts it. Selftest runs them in a closed operation of kind `teardown` (class B, planned with no writers, so a failed teardown stops nothing).

### 3.4 Resume, abandon, auto-abandon

`resume <i>`: orphan check first (F15; exited task containers become evidence and are removed, [ARCHITECTURE.md](ARCHITECTURE.md) §4.5). A close already decided (step 0, §3.1) is finished as decided. Otherwise take the first step without `done`:

- **scratch** → discard its partial outputs (stage, its isolated containers, an unpromoted generation it created) and redo it from the first step of its group; when this operation's isolated project still holds containers, it is taken down first (`compose down`, never `-v`, re-proved as for `Teardown`) and the redo starts at the first step that acted on that project or created a generation. A `CaptureBundle` seal left at `intent` whose bundle is already catalogued with the hash of its published `SHA256SUMS` is observed as done instead (§3.3), so a resume never seals a second bundle;
- **reversible** → observe; `done` → record done; otherwise redo;
- **forward and `idempotent`** → re-run;
- **forward with `observe = "schema"`** → run the schema observation: target schema reached → done; source schema → not started, redo; anything else → stays `unknown`, exit 4 (Planned M3: `resolve`, class D, records the owner's decision). The M1 executor does not run this observation yet: it never repeats such a step, resume stops with exit 4, and `status` names `abandon`;
- a step already journaled `failed` or `cancelled` (seen before a crash, or decided by orphan evidence) → the failure rules, as if seen now.

A terminal task's operation resumes in the CLI on the terminal that runs `resume`, never in the detached executor ([ARCHITECTURE.md](ARCHITECTURE.md) §4.3).

`abandon <i>`: undo reversible done steps in reverse, tear down scratch (isolated projects; generations this op created and never promoted, through a closed deletion of op-labelled objects), and close `abandoned`. If a forward step completed or is `unknown`, writers stay stopped and the instance becomes `frozen`.

**Auto-abandon** (operations without a forward step): `prepare`, `backup`, `verify` and the drill contain only scratch and reversible steps by construction (backup tasks are scratch, §3.3). When a command finds such an operation open and no task container of it is alive, it abandons it: it undoes reversible done steps (writers an offline backup stopped are started again on the recorded deployment), tears down scratch with a recorded teardown, and proceeds. A crashed nightly backup therefore never blocks the next one. `status` keeps the abandoned operation visible and `scheduled` reports it in its output line.

### 3.5 Unknown outcomes

| Where | Rule |
|---|---|
| An undeclared non-zero exit of a task with effect `read` | `failed` |
| An undeclared non-zero exit of a task with effect `app-write` or `data` | `unknown`, never `failed` |
| A declared `unknown` (for example the PostgreSQL consumer's exit 2 of its migrate, role-provisioning and grant tasks) | resolved by `observe = "schema"` or an idempotent re-run |
| A step in an isolated project or on an unpromoted generation | scratch: discard and redo on resume; a running executor treats a scratch step's `unknown` as `failed` |
| A failure before the forward point whose undo or teardown did not complete (for example writers that could not be started again) | `needs-review` (exit 4) instead of `failed-unchanged`; the result lists the warnings |
| A task container that cannot be proved stopped after a timeout or a cancel | the step stays `unknown` with code `task-running` and the operation stays open (exit 4); `next` is the exact `docker stop` (F15) |
| A one-step `app-write` task (for example a password-reset task's declared `unknown` exit 2, or an `ok` exit whose stdout fails the task's `expect`) | the operation closes `needs-review` (exit 4); it does not freeze the instance or block other operations; `status` shows it |

### 3.6 Instance states

```
(none) ─init─► registered ─deploy (first install)─► running ⇄ stopped        (start / stop / restart)
registered ─restore (class C; an adoption imports its payload first, §4.16)─► running [+ adopted_from]
           | registered (failed-unchanged; g1 torn down) | frozen (restore deployment recorded before its start, §4.10)
running | stopped ─deploy | rollback | restore─► [operation open] ─► running | previous state (failed-unchanged) | frozen
frozen ─deploy (forward) | restore | rollback (M3) | resume─► running        start is refused; `start --unfreeze` is class D
running ─restore of an app with side_effects.after_restore = "held"─► running + held_since   (cleared by the clear_hold task)
any ─purge (M3)─► purged                                                      records, bundles, secrets and lock are kept
```

**The way forward from frozen.** When the newest deploy of the instance froze it (it ended `failed-frozen`, or was abandoned past its forward point) after its pre-change bundle was sealed and recorded `verified`, that deploy prints its own command as `next`, and `deploy <i> <ref>` of the same candidate over the same current deployment plans only `VerifyBundle` of that bundle → migrate (the forward point, with the capture's `{freeze_at}` and `{bundle.*}`) → the activation groups → checks → `Record`, pairing the new deployment with that bundle. A way forward that freezes again, or fails with nothing changed, can be planned again. It is refused (`frozen`; the way back is the restore of a pre-change bundle, M2) when the bundle was pruned or is no longer verified, when the migrate task is not `idempotent` (its last run may have ended `unknown`, F5), or for any other candidate. While an instance is frozen, retention keeps that bundle (§5.6); `backup` refuses (`frozen`, `next` the way forward), because the recorded release's tasks would capture data that may be past the forward point; `start`, `stop`, `restart` and write tasks refuse; read tasks, `verify` and drills run. A first install that ended frozen is deployed again on the `g1` it created.

`disposable` is fixed at `init` and recorded in `record.json`; a later edit of `instance.toml` that changes it is refused.

## 4. Operations

### 4.1 `host init` and `init`

- `host init` (once per host, host lock, in the CLI, approved by typing the host name): record engine ID, DockerRootDir, versions, architecture, host capabilities (CPU CFS quota, memory limits), the runc, storage-driver, image-store, logging-driver and cgroup facts ([ARCHITECTURE.md](ARCHITECTURE.md) §11), roots, pools (isolation subnet pool `10.250.0.0/20`, carved into `/24`s, [ADR-0030](adr/0030-isolation-pool-outside-docker-default-pools.md); and the port pool `20000-29999` for `port` params left to allocation; [ARCHITECTURE.md](ARCHITECTURE.md) §7.4), and verify the roots' owner and mode (`INGAT_ROOT` `root:root 0700`, `INGAT_BACKUPS` root-owned with no group or other write bit; else `roots`, nothing written). It creates the tool's empty Docker client directory `cache/docker-config/`, `plans/`, `host/` and `inbox/`. A re-run on the same engine refreshes the facts and keeps the first recorded pools; another engine ID stops it (`engine-mismatch`, exit 2; `host rebind` is M4).
- `init <i> --config <file> --ref <ref>` (class C, host lock, in the CLI, approved by typing the instance name, nothing in Docker touched; gate tier 2): the owner writes `instance.toml` first. Ingat fetches the source, resolves the ref, reads the manifest at that commit and validates the instance against it, then checks: name syntax; no Compose project of that name on the daemon (any container, network or volume labelled `com.docker.compose.project=<i>` refuses `foreign`, even one with the Ingat label, because no record of that instance exists); unique ports and subnets against every allocation entry, every published port, every network's IPAM config on the daemon and the isolation pool; `exclusive_environments` (§4.3); an app this release can run (otherwise `not-in-this-release`); in M1 every `subnet` param set in `instance.toml` (a subnet left to allocation is refused); no data or records of an earlier instance of that name (`exists`); secrets generated as declared (pairwise distinct). It writes `record.json` (state `registered`, a new lineage id, `disposable`) last, after the allocation entries, the secrets and the placeholder directory, so a re-run with the same config finishes an interrupted `init` and keeps the secrets it already wrote.

### 4.2 `prepare <i> <ref>` (class B)

Fetch into the bare clone, resolve the ref once to a 40-hex SHA, check the manifest's `tag_pattern` and the instance's `accept` pattern, export with `git archive` into `cache/src/<sha>/`, read and validate the manifest at that commit (the exported manifest bytes must equal the validated ones, so `.gitattributes` cannot change them: `unsupported-source`), apply the raw-text rules to its Compose files before any Compose call reads them ([ARCHITECTURE.md](ARCHITECTURE.md) §9.5), then:

- pull every image of the candidate once by the reference its Compose service names, rendered with the instance's params (owner decision OD-11, [ADR-0026](adr/0026-app-images-built-in-app-ci.md): app images are built in the app's CI; Ingat never builds). A reference by digest that is already present is not pulled again. Images of `build_services` must match `expect_labels`, which bind the commit; a tag with other provenance is refused;
- record every image's ID and repository digest (for example the PostgreSQL consumer's pinned `postgres` image as well as its own images);
- for image sources: pull `repo@sha256:…` and verify `RepoDigests`;
- write `candidates/<sha>-<refs>.json`, keyed by the commit and a hash of the rendered image references (a param that changes a reference gets a new candidate, never a stale one), and write-once ledger entries (`host/images/<id>/<instance>-<seq>.json`), without the host lock. A recorded candidate whose images are gone (for example after a manual image prune) is pulled again by its recorded digests.

`deploy` runs `prepare` first when no candidate exists for the commit; without a terminal it refuses before preparing anything (its own approval needs one).

### 4.3 `deploy` — first install (state `registered`)

Plan: candidate prepared; no object in the instance's Compose project that is not its own (`foreign`, F8; every deploy, `start`, `stop`, `restart` and a backup that stops writers check it, because Compose acts on everything its project holds); capacity (2 GiB floor on the Docker root); every model passes the policy, host-capability checks included ([ARCHITECTURE.md](ARCHITECTURE.md) §9.5); `exclusive_environments`: an instance whose environment is listed refuses to deploy or start while any other instance of the same app is registered on the host, and other instances of the app refuse `init` while a listed one exists (for an app whose own deployment rule forbids any other instance of it on a daemon that runs its production instance; owner decision OD-5).

Steps: `CreateGeneration g1` for each store (volume with labels; bind directory with the manifest's owner and mode) → the manifest's `[[install]]` steps in order (`start` = `Up` with optional param overrides and waits; `task`; `pause`, which leaves the operation `paused` and allows only the listed tasks until `resume`) → smoke → image identity check → `Record` deployment 1 (`writes_reopened_at` at the `reopens_writes` step; for a probe-based `[schema]`, the value the probe reported at activation, with its time). A task the pause allows is journaled as a step of this operation ([ARCHITECTURE.md](ARCHITECTURE.md) §4.3). Install never captures logs of a service during a window marked `log_snapshot = false` (an app may print a one-time first-run secret to its log).

### 4.4 `deploy` — data-changing update

A deploy is data-changing when the image of any writer or data service differs from the current deployment, or the app declares `migrates_on_start` and any image changes (the SQLite consumer migrates at start). This rule needs no candidate probe at plan time (ADR-0017; owner decision OD-4).

Plan-time schema gate: when the target commit was deployed before on this instance and its recorded expected schema is older than the current actual schema, the plan refuses as "code-only rollback impossible" and prints the restore command for the paired pre-change bundle. Unknown targets are guarded by the apps themselves: the PostgreSQL consumer's migrate refuses an unknown revision with exit 1, and the SQLite consumer refuses a schema newer than it knows.

| # | Step | Class | On failure |
|---|---|---|---|
| 1 | `RunTask` baseline tasks on the current images (recorded, findings allowed; **Planned M3**, the input of a comparison postcheck, owner decision OD-7) | scratch | failed-unchanged |
| 2 | `RunTask` prechecks, each on the image set its task declares (`current` or `candidate`); each must be `ok` | scratch | failed-unchanged |
| 3 | `SnapshotLogs` of `log_snapshot` services | scratch | continue |
| 4 | `Stop` writers; record `freeze_at` (UTC, `YYYY-MM-DDTHH:MM:SSZ`, the grammar the PostgreSQL consumer's migrate accepts) | reversible | undo |
| 5 | `Up` data services if not running, wait for store readiness (F16) | reversible | undo |
| 6 | `CaptureBundle(pre-change)` with the **current** release's tasks and images, schema read first (§4.7) | scratch | undo → failed-unchanged |
| 7 | `VerifyBundle` (hash plus verify tasks) | scratch | undo → failed-unchanged |
| 8 | capacity re-check | — | undo → failed-unchanged |
| 9 | `RunTask` migrate with the candidate image, this bundle bound and `{freeze_at}` — **forward point** | forward, idempotent, observed | `refused` → undo → failed-unchanged; `unknown` → interrupted |
| 10 | `RunTask` postchecks on the candidate (must be `ok`) | scratch | stop writers → failed-frozen |
| 11 | `Up` activation groups in order with their waits; the group marked `reopens_writes` records `writes_reopened_at` | forward | stop writers → failed-frozen |
| 12 | smoke probes and image identity check (running image ID = recorded ID for every service) | scratch | stop writers → failed-frozen |
| 13 | `Record` deployment N+1 (rollback target N, pre-change bundle id) | idempotent | — |

PostgreSQL consumer mapping (mirrored by `fx-pg`; as its own release procedure without accepting pre-existing findings): prechecks = its full invariant check on the running release, which must be clean, so a pre-existing finding refuses the release before the freeze, plus a narrower invariant check on the candidate; migrate = its migrate one-off service; postcheck = the full invariant check on the candidate after migrate, which must be clean; activation = backend, then web (which reopens writes); web keeps serving the shell while backend is stopped. Accepting pre-existing findings (a baseline plus a comparison postcheck) needs a change in that consumer and arrives in M3 (owner decision OD-7). SQLite consumer mapping (mirrored by `fx-lite`): no checks; migrate is an explicit one-off before the start, so the start applies nothing.

A data-service image change (for example a PostgreSQL bump in a release of the PostgreSQL consumer) is refused before M3 with a clear message. **Planned M3:** class D with an explicit choice, `--data-image in-place` (same on-disk format) or `--data-image via-restore` (restore the pre-change bundle into a new generation under the new image), which also covers PostgreSQL major upgrades.

### 4.5 `deploy` — config-only change

When no writer or data image changes, Ingat compares each service's `compose config --hash` with the running container's `com.docker.compose.config-hash` (labels carry no per-deployment value, so only a real configuration change alters a hash: [ARCHITECTURE.md](ARCHITECTURE.md) §6.2), snapshots logs, recreates only the changed services (`up --no-deps --no-build --pull never <services>`), waits for their probes, runs smoke and records the deployment. A changed owner-gated key (for example the SQLite consumer's outbound-mode and real-sending switches) makes the plan class D and shows the change prominently.

### 4.6 Rollback

- **M1-M2:** `deploy <i> <older-ref>` follows §4.4; the schema gate refuses it when the older release cannot run on the current schema, and the owner restores the paired pre-change bundle with `restore` (§4.10, from M2), which runs the restore task in that bundle's own release image, so no keep-schema mode is needed.
- **Planned M3:** `rollback <i> [--to <seq>]`. *Code-only* when the target deployment's recorded expected schema equals the current actual schema: stop writers, `Up` the target's recorded images, probes, smoke, `Record` (class C). *Data rollback* otherwise: the restore flow (§4.10) with the paired pre-change bundle, the target release, and the manifest's `[rollback] env` (for the SQLite consumer, its job runner switched off, because a schema from before its outbound pause cannot hold jobs). Class D whenever writes reopened since the target, and the plan states the lost-writes window (they stay in the kept generation). `--accept-schema <rev>` (the PostgreSQL consumer's rollback path in which an older release serves one unknown schema revision) sets the manifest's `accept_schema` param on the target deployment, class D.

### 4.7 `backup` (class B; unattended)

Plan: refused while the instance is frozen (§3.6); capacity (§5.8); gate tier 1 allowed only for an online backup (class `scheduled` or `manual` and every store `online_backup`). Retention is gate tier 2: on an uncertified or untested platform `backup --prune` refuses (exit 2), while `scheduled backup` backs up and skips its retention with the recorded warning `retention skipped: …`.

Steps: [`Stop` writers when the store is not `online_backup`, or the class is `pre-change` or `final`] → `Up` data services and wait for readiness (F16) → **schema read**: for a task-based `[schema]`, the schema task as a scratch read step (Planned M2: M1 refuses a capture for such an app, `not-in-this-release`); for a probe-based `[schema]`, the value the deployment record holds from its activation (a running app's schema changes only through a deploy); the result feeds `{schema.expected}` and `bundle.json` → a stage in `ops/<seq>/stage/`, owned by the task's effective uid → the manifest's `backup.steps` in order (stdout streamed into stage files with the `nonempty` check, stdin streamed from stage files, declared mounts) → payload rule: exactly one top-level entry, equal to `backup.payload` when declared; hidden entries Ingat created are removed → `bundle.json`, `SHA256SUMS` and `meta/` → copy into `<backups>/<i>/.incoming-<id>/`, fsync, rename to `<id>/` → catalog record → `VerifyBundle` → [restart writers] → [retention, for `scheduled backup` or `--prune`] → `Record`.

A sealed bundle whose verification fails stays published, with an `ok: false` `verified` record (exit 3); retention never counts it as the newest verified bundle. A busy lock exits 2 and the scheduler mails the owner.

### 4.8 `verify <i> <bundle>|--latest` (class B)

Re-hash the sealed directory (every listed file regular with link count 1; links, special files and unlisted files refused), compare the bundle hash with the catalog record (detects tampering in the backups root), make a private input copy, run the manifest's `backup.verify` tasks, append a `verified` record. A hash mismatch or a failed verify task appends that record with `ok: false` (F10).

### 4.9 `verify … --restore-test` (the drill; class B; unattended)

Plan: capacity (§5.8); `[drill] min_free_memory` against `/proc/meminfo`; gate tier 2; a free pool subnet (the executor allocates it at start: [ARCHITECTURE.md](ARCHITECTURE.md) §7.4); the bundle's recorded release images present (Ingat removes no images before M3; a missing one refuses `missing-image`, and `prepare` of that release pulls it again by its recorded digest).

Steps:

1. `CreateGeneration t<seq>` for each store (`purpose=drill`).
2. Isolated project `<i>--t<seq>`: override with the `t<seq>` stores, internal networks (an app must not rely on a default route there: an app that needs one gets a hold, as the PostgreSQL consumer's web service does; whether one exists differs by Engine, spike S12), no published ports, pool subnets, the manifest's holds, **throwaway** generated secrets in `ops/<seq>/secrets/` (always; with no declared secret, a `secrets_dir` param still gets the directory, holding only an empty `.keep` file; a drill never sees the instance's secrets), and an isolated app env file without owner-gated or secret keys.
3. `Up` `restore.start` services, wait for store readiness.
4. `restore.steps` (bundle files streamed over stdin, or a private input copy mounted).
5. `restore.post` tasks; `restore.checks` and `drill.checks` (each must be `ok`); `drill.record` tasks (recorded, findings allowed).
6. When `drill.activate`: `Up` the activation groups inside the isolated project; `exec` and `health` probes run, `http` probes are recorded as not applicable in isolation.
7. Evidence (timings, outcomes, versions) → a `restore-tested` record bound to the bundle hash; a failed drill appends it with `ok: false` (F10).
8. `Teardown`: `compose down` of the isolated project (never `-v`, re-proved: §3.3), then a closed deletion of its own `t<seq>` volumes and directories, each re-proved (`purpose=drill`, `op=<seq>`, unused), then removal of its subnet allocation entry. Teardown runs on failure too.

The live instance keeps running (owner decision OD-6).

### 4.10 `restore <i> --bundle <id> --reason TEXT`

Class D for an instance with data, class C for one never deployed. The plan prints the bundle's `created_at` and `freeze_at`, the current deployment, and whether writes reopened after the bundle; those writes stay in the kept generation.

A restore always runs in the bundle's own release and leaves the instance on that release; a normal `deploy` then moves forward. Restoring in the current release would need a migrate step inside the restore and has no consumer in v1; it returns by ADR when one needs it.

Steps:

1. Verify the bundle hash against the catalog; target images = the bundle's recorded release.
2. `CreateGeneration g<N+1>` for each store.
3. Isolated project `<i>--r<seq>` with the **real** instance secrets (a fresh PostgreSQL volume initializes with the instance's own owner password; the app's role-provisioning task sets the instance's role passwords), holds, internal networks, no ports, pool subnets, stores bound to `g<N+1>`.
4. `Up` `restore.start` and wait for readiness → `restore.steps` → `restore.post` → `restore.checks` → when `restore.activate`, start the activation groups in isolation and wait for their `exec`/`health` probes.
5. `Teardown` of the isolated project (containers and networks only) and removal of its subnet allocation entry; `g<N+1>` is kept.
6. `SnapshotLogs`; `Stop` the live project (writers first) — reversible. A never-deployed instance has nothing to stop.
7. `SwitchGeneration gN → g<N+1>` (from none to `g1` for a never-deployed instance) — reversible until a writer starts.
8. `Record` the restore deployment N+1 **before its start** (write-once `deployments/<N+1>.json`: origin bundle id, the bundle's release and images) and make it current in `record.json` (with `adopted_from` for an imported adoption payload, §4.16), so the instance always has a recorded deployment that matches its current generation.
9. `Up` the live project with the target deployment's images (plus `[rollback] env` when the restore is a rollback), probes, smoke.
10. `Record` the outcome in `record.json`; for apps with `after_restore = "held"`, set `held_since` and print the manifest's `restore_notice`.

A failure before step 8 switches back if step 7 ran, leaves the old generation untouched and restarts the live project, if there is one (failed-unchanged; a never-deployed instance stays `registered`). Step 8 is the **forward point**: a failure in step 8 or 9 stops writers (failed-frozen) with the pointer on `g<N+1>` and deployment N+1 current, so `start <i> --unfreeze` (class D), `deploy <i> <ref>` and a repeated `restore` all have a deployment to start from; `next` prints `ingat restore <i> --bundle <id> --reason …` (class D now that the instance has data). **Planned M3:** `restore <i> --generation <store>=g<N>` switches back. A CI assertion checks that no live writer ever mounts an unswitched generation and no isolated project mounts the live one.

An `imported` bundle (§5.9, §4.16) is accepted only after it is `restore-tested` on this host. For an imported adoption payload, whose `bundle.json` records no schema, the restore deployment records the schema the way a first install does (§4.3).

The PostgreSQL consumer (mirrored by `fx-pg`): `pg_restore --single-transaction --exit-on-error --no-owner --no-privileges` into the fresh database, then its role-provisioning and grant tasks (its dumps carry no grants), then its schema-revision read must report current and its invariant checks must pass. The SQLite consumer (mirrored by `fx-lite`): a one-off app restore command from the bundle input into the empty generation; the app verifies hashes, integrity and schema and sets its outbound pause.

### 4.11 `start`, `stop`, `restart` (class C)

`start` uses the recorded deployment's pinned image IDs and refuses while frozen (`--unfreeze` is class D), while an operation is open, on an engine-ID mismatch, on an `exclusive_environments` conflict, or, for a task-based `[schema]`, when the schema task (run as a scratch step) shows a pending migration (Planned M2: M1 refuses `start` and `restart` of such an app, `not-in-this-release`). The schema check does not apply to a `migrates_on_start` app with a probe-based schema: its schema cannot be read before it starts, and `start` runs the same pinned image IDs that already ran on this data. `stop` stops writers first, then the rest in reverse activation order. `stop` and `restart` refuse while frozen too (a stopped instance could later start past the unfreeze). A partial `stop <i> <service>…` records no state change. `restart` snapshots logs first (Planned M2, with `SnapshotLogs`).

### 4.12 `task <i> <name>`

Only declared tasks. Read tasks are class B; `app-write` and `data` tasks are class C one-step operations. A task with `operator = false`, an `image` other than `current`, or a `stage`, `bundle` or `generation:<store>` mount (these exist only inside the operations that use them) is refused (`not-operator`). An app's own preview-then-confirm commands are modelled as two tasks: a preview task (without the app's confirm argument; `read` when the app's preview writes nothing, otherwise `app-write` and `idempotent`) and a separate `app-write` task with the confirm argument (the SQLite consumer's outbound commands, [MANIFEST_SPEC.md](MANIFEST_SPEC.md) §11). Ingat does not bind the two invocations; the app's own confirm command re-checks its state. A task's `expect` (§4 of [MANIFEST_SPEC.md](MANIFEST_SPEC.md)) decides whether an `ok` exit really is `ok`. Output classes: `terminal` is shown and never captured (the task runs in the CLI container, [ARCHITECTURE.md](ARCHITECTURE.md) §4.3); `record` is stored 0600 in `reports/` or the op's artifacts; `json` is parsed, bounded and redacted.

### 4.13 `prune`

- `--bundles` (class B; M1): retention (§5.6). Dry-run by default; `--apply` and `scheduled backup` apply it.
- `--generations` (class D; Planned M3): lists non-current generations older than the pin window; never the current or the previous generation.
- `--images` (class D, host scope; Planned M3): only ledger images with no reference from a retained deployment or a pinned bundle.

### 4.14 `purge <i>` (class D; Planned M3)

1. `CaptureBundle(final)` with writers stopped.
2. Drill of exactly that bundle until `restore-tested`; skipped for `disposable` instances, and the confirmation screen says so.
3. A closed deletion plan: containers, networks, generation volumes, bind generations, isolated leftovers, unreferenced Ingat-tagged images.
4. Typed challenge `PURGE <i> <4 chars>`.
5. `Delete` each item, re-proved.
6. State `purged`; bundles, records, verifications, secrets and the lock are kept.

### 4.15 Diagnostics

- `status [--json]` reads records first (deployment, generations, open operation and its last step, `held_since`, last bundle and its verification ages, last restore-test age), then live Docker data, reported separately when unavailable: service state, health, restart counts, image-ID and config-hash drift, foreign objects, free space on every root and the Docker root, gate tier. `changed-outside` attention means a deployed instance's containers, networks or generation volumes are missing or differ from the recorded deployment (for example after a Container Manager "Clean": [ARCHITECTURE.md](ARCHITECTURE.md) §11.2); it ships with `status` in M1. `uncertified` attention means no certification matches the host's platform build ([ARCHITECTURE.md](ARCHITECTURE.md) §3.6): gate tier 2, scheduled drills included, refuses until `selftest --host` certifies the build. Every JSON answer carries `next`, the exact command to run. Exit 5 when attention is needed.
  - Attention codes, most important first (the answer's `next` serves the first present): `daemon-unreachable`, `engine-mismatch`, `invalid-config` (an instance whose `instance.toml` or records do not load; `status` with no name and `scheduled status` report the others too; `next` is `status <i>`, which names the errors), `open-operation`, `frozen` (`next` is the way forward when it can be taken, §3.6, else `history <i>`), `last-op-failed` and `needs-review` (`next` is what that operation's result printed, or `history <i>`), `changed-outside`, `foreign`, `drift`, `held`, `unverified-bundle`, `backup-old`, `restore-test-old`, `uncertified`.
  - An open operation counts as running, not as attention, while an executor of the instance runs it (the host executor for a selftest instance) or, for a terminal task the CLI runs, while its task container runs a step in flight. A task container that outlived its executor makes `next` its exact `docker stop`. `history` shows an open operation as running, paused or interrupted.
  - A container stopped by a completed `stop` of its service (Docker's finish time within that operation) is not `changed-outside`.
- `doctor <i>` adds policy and gate checks (certification included), secret-file shape, port and subnet collisions, root owner and mode, the observed proxy peer address compared with the configured trusted-proxy value when the manifest names one (as the SQLite consumer's does; not in M1 code yet: no manifest key names that value), and capability availability (for example "restore: not applicable" for a stateless site).
- `scheduled status` (class B, unattended, M1-M2; replaced by `check` in M3) computes the same attention codes as `status` for every instance and compares the set with `host/attention.json`, the only file it writes. It exits 5 and prints the new and cleared codes only when the set changed since its last run; otherwise it exits 0 and prints nothing. So a lasting condition (an app `held` after a restore, an old drill) mails the owner once, not every run.
- **Planned M3:** `check` (the scheduled monitor, at parity with the PostgreSQL consumer's own monitoring script): container health and restart deltas, the ready predicate over the published port, certificate expiry of the public URL, disk thresholds, backup and restore-test age, open operations; dedupe state in `instances/<i>/monitor.json`, the only file `check` writes.

### 4.16 Adoption — take over a deployment Ingat did not create (Planned M4)

Adoption brings an app deployment that Ingat did not create (started by hand, from Container Manager or by another tool) under a new Ingat instance, **from a payload of the app's own backup command**. Ingat never touches a foreign object: it does not stop, start, exec into, mount, relabel, restore into or delete one (F8; ADR-0024). Docker cannot change the labels of an existing object, so a foreign object never becomes owned; its data moves into a new instance through an imported bundle and the restore of §4.10. Adoption reads no label, record or bundle of the earlier in-house deployment controller (ADR-0001).

**Precondition.** The app has an `ingat.toml` at a release whose `restore` tasks read what the foreign deployment's backup command writes, normally the release the foreign project runs. Adoption never migrates on its own: the restore runs in the stated release, and the app's restore and checks refuse a schema that release cannot run (onboarding checklist item 2, [ARCHITECTURE.md](ARCHITECTURE.md) §11.3). An app without a backup command the owner can run against the foreign deployment waits for the deferred `cold` strategy (§5.1).

**Runbook** (operator guide, M4). The steps outside Ingat use the foreign project's own tooling and are the owner's; operations agents never run them (`docker` is in their deny rules: owner decision OD-10).

1. **New instance.** Write `instance.toml` for a new instance with its own name, ports and subnets (the foreign project keeps its own until the owner removes it), set declared secrets with `secret set`, run `init <i> --config <file> --ref <release>` and `prepare <i> <release>`. Params that name data inside the stores (for example a database name or owner role) equal the foreign project's values, taken from its own configuration. Nothing is taken from the foreign project's secrets.
2. **Quiesce and export, outside Ingat.** Clear the restart policy of the foreign containers (`docker update --restart no <ids>`), so a daemon restart cannot start them again (live restore is off by default, and off in Container Manager 24.0.2-1706); a container with `HostConfig.AutoRemove` is deleted by its stop together with its anonymous volumes, so check before stopping. Stop the foreign writers, run the app's own backup command against the foreign project (its data services may keep running for that) and place its output in a new directory under `INGAT_ROOT/inbox/`, then stop the rest of the project (`docker compose -p <project> stop`; never `down -v`, never a vendor GUI's project actions such as Container Manager's "Clean" or "Delete").
3. **Import.** `ingat import --payload <dir> --into <i> --release <ref> --from <name> [--id <bundle-id>] --reason TEXT` (class B, below).
4. **Drill.** `ingat verify <i> <bundle> --restore-test`; `restore` refuses an imported bundle that is not `restore-tested` (§4.10).
5. **Cut-over.** `ingat restore <i> --bundle <bundle> --reason TEXT` (class C, because `<i>` was never deployed: §4.10); the owner repoints the reverse proxy to the new instance's port right after it completes. Downtime runs from the writer stop in step 2 to this point.
6. **Acceptance.** Once the new instance has run and its first scheduled bundle is verified, the owner removes the foreign project by hand (its volumes only when the owner chooses).

**`import --payload`** (class B: it writes only a new bundle). Plan (pure; a refusal leaves no trace, F2): `<i>` is `registered` (never deployed) and a candidate for `<ref>` is prepared; `<dir>` lies under `INGAT_ROOT/inbox/` and holds exactly one top-level entry; the bundle id is that entry's name unless `--id` gives one, matches the id grammar (§5.4) and is unused; when the manifest declares `backup.payload`, its rendering with that id equals the entry name (the payload rule of §4.7); capacity as for a backup (§5.8). Steps: copy `<dir>` into the stage with a no-follow walk (links, special files and unsafe paths refused) → `bundle.json` with `class = "pre-change"`, `consistency = "external"` (produced outside Ingat; its consistency is the owner's statement), no `freeze_at` and no `schema`, `deployment = {seq: none, release and commit of <ref>, images: the prepared candidate's IDs}` and `origin = {adopted_from: <name>}` (§5.3) → `SHA256SUMS` and `meta/` → seal, publish and catalog as `imported` (§5.9) → `VerifyBundle`, whose `backup.verify` tasks run on the candidate images. `--from <name>` is the owner's label for the foreign project; Ingat records it and never inspects the project. In the drill and the restore, `{image.<service>}`, `{release}` and `{commit}` render the bundle's recorded deployment, the candidate ([MANIFEST_SPEC.md](MANIFEST_SPEC.md) §3). The restore deployment records the bundle as its paired pre-change bundle, so retention keeps it while that deployment is current or previous (§5.6).

**Rollback before acceptance.** `ingat stop <i>`; then, with the foreign project's own tooling, restore its restart policy and start it; repoint the reverse proxy. Writes made in the new instance stay in its generation and are not carried back. Start the foreign project only after the new instance's writers are stopped: two running copies of one app mean two outbound queues for an app with outbound side effects. Moving forward to a newer release is a normal `deploy` with its own pre-change bundle.

**Floors.** F2 (`import` and its plan leave no trace on refusal), F6 and F7 (a sealed, verified and restore-tested bundle exists before the cut-over; the restore fills the new instance's first generation), F8 (no foreign object is touched; the CI adoption suite checks the Docker events: [ARCHITECTURE.md](ARCHITECTURE.md) §10.3), F13 (the drill and the restore staging are isolated as usual).

## 5. Data

### 5.1 Strategies

| Strategy | Use | Status |
|---|---|---|
| `tasks` | App-native task steps inside the app's own images (both reference consumers). Ingat owns quiescence, staging, hashing, sealing, verification, retention and the drill. | Decided, M1 (the SQLite consumer), M2 (the PostgreSQL consumer) |
| `none` | Stateless apps; backup, verify, restore and drill report "not applicable". Rollback means the previous digest or commit. | Decided, M1 |
| `cold` | Stop the project, copy declared stores with a helper container, restore only with the same data-image ID. | Deferred; trigger: a consumer without app-native hooks, an app to adopt whose backup command the owner cannot run against its foreign deployment (§4.16), or an observed need for an emergency copy that app hooks cannot make |

### 5.2 Stores and generations

- Each store binds to generation `g<N>`: a volume `<i>_<store>_g<N>` created and labelled by Ingat and declared `external: true` in the override, or a directory `INGAT_ROOT/data/<i>/<store>/g<N>/` with the manifest's owner and mode and a marker `g<N>.json` beside it.
- Drills use `t<seq>` generations. Restores, data rollbacks and data-image moves create `g<N+1>`. The previous generation stays until `prune --generations` (Planned M3).
- This is the pattern both reference consumers already follow by hand: the PostgreSQL consumer restores into a new database; the SQLite consumer restores into an empty directory.
- A failed restore costs nothing, which replaces the old "emergency capture" class.

### 5.3 Bundle format (directory, format 1)

```
<backups>/<instance>/<bundle-id>/
  bundle.json      format, id, class, instance, app, environment, lineage, created_at, freeze_at, consistency
                   (writers-stopped | online-app | external), deployment {seq, release, commit, images {service: id},
                   manifest_sha256, model_sha256}, schema {expected, actual}, stores {name: generation},
                   payload {entry, files [{path, size, sha256}], total_bytes}, meta [...],
                   tool {version, engine, api, cli, compose, arch, os}, host,
                   origin (optional, M4: {adopted_from: <name>} for an imported adoption payload, §4.16)
  SHA256SUMS       bundle.json and every payload and meta file
  payload/<entry>/ what the app's backup tasks produced: exactly one top-level entry
  meta/            ingat.toml and the Compose files of that commit, deployment.json (non-secret)
```

The **bundle hash** is the SHA-256 of `SHA256SUMS`. It is recorded in `instances/<i>/catalog/<id>.json` (root-only), so a swapped or edited bundle in the backups root is detected on every use. Verification records live in `instances/<i>/verifications/<bundle-id>.json`, one append-only JSON Lines file per bundle outside the sealed directory, so the hash is not circular. A bundle never contains secrets, env files or the resolved Compose model. An imported adoption payload (M4, §4.16) records `consistency = "external"`, no `freeze_at` and no `schema`, and a `deployment` with no `seq` whose release, commit and image IDs are those of the prepared candidate, so `{image.<service>}` renders the candidate's IDs in its drill and restore.

### 5.4 Bundle ids

The id comes from the manifest's `[backup.naming]` template for the class (default `{bundle.stamp}-{class}`; an imported adoption payload uses its entry's name or `--id`, §4.16), must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, and must not exist. Classes: `scheduled`, `manual`, `pre-change`, `final`. Behaviour never depends on the id text; the class is recorded in `bundle.json` and the catalog. An app with its own backup-name grammar maps the classes onto it in its manifest: the PostgreSQL consumer's grammar is a UTC stamp followed by a daily, manual or labelled pre-release suffix (the label is required for pre-release and forbidden otherwise), so its own backup-publishing command and its migrate's pre-change-backup check accept Ingat's bundles unchanged (`fx-pg`: `backup-publish --name {bundle.id}`, `migrate --pre-change-backup {bundle.payload}`, [MANIFEST_SPEC.md](MANIFEST_SPEC.md) §8). A conformance test (M3) covers the mapping and `{freeze_at}` against the app's real migrate freeze-time guard.

### 5.5 Verification levels

| Level | Meaning | Needed by |
|---|---|---|
| `verified` | the bundle hash matches the catalog and every `backup.verify` task returned `ok` (an app without a read-only verify command, such as the SQLite consumer today, gets hash-only verification) | a data-changing deploy (its own pre-change bundle) |
| `restore-tested` | the drill (§4.9) passed restore, post tasks, checks and probes | purge of a non-disposable instance; `status` flags one older than `restore_test_max_age_days` |

Only records bound to the catalogued bundle hash count, and per level the newest one decides: a failed verify or drill appends `ok: false`, so a bundle whose newest record at a level failed is no longer counted at that level (`status` shows `unverified-bundle`).

### 5.6 Retention (`prune --bundles`)

Calendar windows in UTC: `keep_daily`, `keep_weekly`, `keep_monthly` (restic vocabulary). Always kept: the newest bundle, the newest verified bundle, the newest restore-tested bundle, pre-change bundles younger than `pin_pre_change_days`, pre-change bundles paired with the current or previous deployment, the pre-change bundle of the update that froze the instance while it is frozen (its way forward and its restore need it, §3.6), and anything an open operation references. Retention is gate tier 2 ([ARCHITECTURE.md](ARCHITECTURE.md) §3.6; a `scheduled backup` skips it with a warning, §4.7). A deleted bundle is renamed aside, removed and recorded by a tombstone `catalog/<id>.pruned.json`. Retention acts only on catalogued bundles; it refuses the whole run when any bundle is dated after the host clock (a rule taken from the SQLite consumer's own backup runbook); it never deletes an unverifiable bundle; deletion is a closed plan of catalog entries. App-side pruning (both reference consumers have their own) is never used under Ingat.

### 5.7 Side effects and holds

Every isolated run (drill, restore staging) applies the manifest's `[holds.<service>]` as Compose `environment` overrides, which beat `env_file` values; drops owner-gated and secret app-env keys from the isolated env file; makes every network internal; publishes no ports. For the SQLite consumer (mirrored by `fx-lite`) the holds set its outbound mode to capture and switch its job runner off; its real-sending switch and the SMTP credentials are dropped, so even a hold bug cannot reach SMTP. Holds also cover startup needs of isolation: the PostgreSQL consumer's web service (mirrored by `fx-pg`) derives its trusted proxy address from the default IPv4 route and exits without one, and an internal network may have none (it differs by Engine: spike S12), so its hold sets that address to `127.0.0.1` (any IPv4 address works: no proxy traffic exists in isolation).

Apps with `side_effects.kind = "outbound"`:

- restore only through their own restore task (`restore_via_app = true`): the SQLite consumer's restore sets its outbound pause with reason `restored` and holds queued sends;
- after a live restore the instance shows `held_since` until the `clear_hold` task (for the SQLite consumer, its confirmed command that resumes outbound sending) succeeds; `restore_notice` points at the app's reconciliation tasks;
- the live project is stopped before the switch, so two production queues never run on the same data;
- `single_active` (Planned M4, with restore into a new instance): writers of two un-isolated instances of the same lineage never run at once.

### 5.8 Capacity

Checked before any effect, **grouped by filesystem** (`st_dev` of `INGAT_BACKUPS`, `INGAT_ROOT` and the `ingat-probe` volume for the Docker root) and summed: all three often sit on one filesystem (the root filesystem of a small Linux host; `/volume1` on DSM), so the stage, the published copy, a drill's input copy and its restored store add up on one filesystem. Per operation:

| Operation | Needs (S = expected payload size) |
|---|---|
| backup | S for the stage (`INGAT_ROOT`) + S for the published copy (`INGAT_BACKUPS`) + 1 GiB floor per filesystem |
| drill, restore | S for the input copy (`INGAT_ROOT`) + 2 × S for the restored store (generation location: `INGAT_ROOT` for bind stores, the Docker root for volumes) + 1 GiB floor per filesystem |
| import of an adoption payload (M4) | as backup, with S measured from the payload directory |
| prepare (pulls), first install | 2 GiB floor on the Docker root |

A root or the probe mount that does not exist cannot be measured and refuses (`cannot-measure`, exit 2). S is the newest catalogued payload of the instance. Before the first bundle it is estimated from the measured store size: the bind generation's size from a no-follow walk, or the volume's size from `docker system df -v` (read-only). Ingat never deletes anything to make room.

### 5.9 Off-host copies

Delegated to the platform's tools, outside Ingat. After the nightly backups, a copy of `INGAT_BACKUPS` goes to an owner-managed destination off the host, encrypted client-side. On a Linux host that is restic (with an append-only remote and an offline recovery key; `forget`/`prune` run from a trusted client) or borg, both of which encrypt client-side, or rsync to an encrypted destination. On DSM, a Hyper Backup task protects the `ingat-backups` shared folder with client-side encryption, to another NAS or an off-site target. Recovery never relies on snapshots (on DSM, Snapshot Replication exists only on Btrfs volumes: [ARCHITECTURE.md](ARCHITECTURE.md) §11.2), so the sealed bundles plus this copy are the whole recovery path. Anything coming back from off-host re-enters only through `import` (Planned M4): copy, verify every listed file, reject links, special files, unlisted files and unsafe paths, catalog as `imported`, then drill before any live use.

## 6. Exit codes (every command)

| Code | Meaning |
|---|---|
| 0 | completed |
| 1 | refused; nothing changed (invalid input, policy, stale plan, capacity, wrong state) |
| 2 | could not run; nothing changed (daemon unreachable, lock busy, open operation, untested platform for this tier, usage errors such as a bad instance name, argument or path, no terminal for a typed approval, an expired plan, an unmeasurable root) |
| 3 | failed after effects, a cancel after effects included (code `cancelled`); the instance is in a recorded safe state (`failed-unchanged` or `failed-frozen`); `status` shows `next` |
| 4 | an operation needs attention (paused, interrupted, unknown, needs-review); run `ingat status <i>` |
| 5 | findings (status, verify or read-only check tasks found something; nothing failed) |
| 130 | cancelled before any effect |

Every JSON result also carries a stable machine `code` string and `next`; a refusal or failure also carries its message, including one the executor decided.

## 7. Scheduled jobs

The host's scheduler runs every job as root without a terminal and mails the owner when a job exits non-zero: systemd timers (a oneshot service per job with an `OnFailure=` unit), cron as a fallback (`MAILTO`), or the platform's own scheduler (on DSM, Task Scheduler with a user-defined script, user root, "send run details by email only when the script terminates abnormally"). Every entry calls the wrapper by absolute path. `scheduled` refuses class C and D plans and terminal tasks (`unattended`, exit 2), prints one line on success (naming an operation it auto-abandoned) and a redacted summary on stderr on failure. Example schedule for a host with a SQLite-consumer test instance `lite-test` and a PostgreSQL-consumer staging instance `pg-staging`, under the default root (on DSM the wrapper is `/volume1/ingat/bin/ingat`):

| When | Command |
|---|---|
| daily 01:30 | `/srv/ingat/bin/ingat scheduled backup lite-test` (class `scheduled`, then retention) |
| daily 02:00 | `/srv/ingat/bin/ingat scheduled backup pg-staging` |
| daily 03:00 | Off-host copy of `INGAT_BACKUPS` by the platform's tool (restic, borg or rsync on Linux; a Hyper Backup task on DSM), outside Ingat (§5.9) |
| daily 04:00 | `/srv/ingat/bin/ingat scheduled task pg-staging check` (read-only; report 0600; exit 5 on findings) |
| Sunday 05:00 | `/srv/ingat/bin/ingat scheduled verify lite-test --latest --restore-test` |
| Sunday 06:00 | `/srv/ingat/bin/ingat scheduled verify pg-staging --latest --restore-test` |
| hourly | `/srv/ingat/bin/ingat scheduled status` (exit 5 and mail only when the attention set changed, §4.15); replaced by `check` in M3 |

Job times stay apart: a busy lock exits 2 and is mailed, never queued. After a platform update (on a Linux host, every reboot into a new kernel) a drill exits 2 and is mailed until `selftest --host` certifies the new build, while the backups continue and skip their retention with a recorded warning ([ARCHITECTURE.md](ARCHITECTURE.md) §3.6). **Planned M3:** `ingat schedule render <i> --systemd` prints oneshot units, timers (`Persistent=true`) and an `OnFailure=` unit; `--cron` prints crontab lines as a fallback; `--dsm` prints the Task Scheduler entries to create.
