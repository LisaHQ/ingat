# Ingat app manifest and instance config

Status: **Decided** as a draft of manifest schema 1 and instance schema 1; frozen at the M2 exit gate. Nothing is implemented. The whole schema parses from v0.1, but M1 honours only the keys the SQLite consumer and the fixtures use (§11, §12); keys only the PostgreSQL consumer needs (§8-§10) are honoured from M2 and may still change during its onboarding, before the freeze (`ROADMAP.md` §3). Keys marked **Planned Mx** parse from v1 but are honoured only from that milestone. The examples in §8-§13 are the fixture forms of the acceptance inputs (§7): they, and the consumers' own manifests they mirror, must validate and run unchanged at the M2 exit gate, and a core change they force after the schema freeze is recorded as a generality failure (ADR-0021).

## 1. Two files, two owners

| File | Lives in | Owner | Holds | Read |
|---|---|---|---|---|
| **App manifest** `ingat.toml` | The app repository root (path configurable per instance) | App developers | Topology facts: Compose files, release identity, service roles, stores, params (types only), secrets (declarations), app-env keys, probes, smoke checks, tasks, backup/restore recipes, holds, side effects, install steps | From the exact commit being deployed (`git show <sha>:ingat.toml`), snapshotted per deployment. A rollback automatically uses the matching manifest. |
| **Instance config** `instance.toml` | `INGAT_ROOT/instances/<name>/` (root 0600) | Owner | Values: name, app, environment, source, param values, app-env values, retention, monitoring | Snapshotted per operation; Ingat never rewrites it |

Image-sourced apps (stateless sites without a repository) keep `ingat.toml` and their Compose file in `INGAT_ROOT/instances/<name>/app/`, hashed per deployment.

An app manifest lives in the app's own repository, which may be public, so it is generic: tasks, services, probes and param declarations, never host values. Everything host-specific (ports, subnets, URLs, hostnames, repository credentials, secrets) lives only in `instance.toml`, secret files and deploy keys on the host, plus the owner's offline encrypted copy (owner decision OD-9).

Both files are TOML 1.0, parsed with `tomllib`; unknown keys are refused at every level. The word "manifest" means the Ingat app manifest (deliberately not "profile": apps use Compose `profiles:` for task-only services, as `fx-pg` does with `profiles: [ops]`); Compose's own `profiles:` are called "Compose profiles". An app's own backup manifest (a file an app writes into its own backup directory, as `fx-pg`'s `backup-publish` does) is always called that in full.

## 2. App manifest schema 1

### 2.1 Top level and `[source]`, `[compose]`

| Key | Type | Meaning |
|---|---|---|
| `manifest` | int | Schema version, `1` |
| `app` | string | App id, `^[a-z][a-z0-9-]{1,30}$` |
| `requires_ingat` | string | Version range, for example `">=0.1,<1"` |
| `exclusive_environments` | list | An instance whose environment is listed refuses to deploy or start while another instance of this app is registered on the host, and vice versa for `init` (`LIFECYCLE.md` §4.3) |
| `[source] kind` | `"git"` \| `"image"` | Build from an exact commit, or deploy image digests |
| `[source] release` | `"tag"` \| `"commit"` | What names a release (git only) |
| `[source] tag_pattern` | regex | Allowed tags when `release = "tag"` |
| `[source] images` | table service → param | Image sources only: which `image` param feeds which service |
| `[compose] files` | list | Runtime Compose files, in merge order |
| `[compose] build_files` | list | Files used only by `prepare` to build (git only) |
| `[compose] build_services` | list | Services built by `prepare`; every other image is pulled by tag once and pinned by ID. Pending owner decision OD-11 (where app images are built): if images are built in the app's CI instead, `build_services` are pulled by digest and checked with `expect_labels`; the key that names the source is defined by the M0 ADR |
| `[compose] build_env` | table | Variables for the build invocation only (templated) |
| `[compose] expect_labels` | table | Image labels that must equal the templated values, or the image is refused (provenance of reused tags) |

### 2.2 `[params]`

Every Compose variable without a Compose default (`${VAR}`, `${VAR:?…}`) must be declared; variables with a Compose default (`${VAR:-x}`) may be declared to let the instance set them, otherwise they are never set. Each entry is a table:

| `kind` (default `string`) | Value comes from | Extra keys |
|---|---|---|
| `string` | instance `[params]`, else `default` | `required`, `default`, `optional` (unset leaves the Compose default), `pattern` |
| `template` | the manifest, rendered per invocation | `value` (template, §3) |
| `port` | instance value or allocated; unique per host; published on `127.0.0.1` only | — |
| `subnet` | instance value or allocated `/24`; unique per host; isolated runs get pool values | — |
| `secrets_dir` | `INGAT_ROOT/instances/<i>/secrets` | — |
| `env_file` | the rendered app env file of the deployment (0600) | — |
| `store` | the current generation directory of a bind store | `store` |
| `task_dir` | the stage or private input copy of the task that binds it; the empty `placeholder/` otherwise | — |
| `accept_schema` | empty, except when `rollback --accept-schema` sets it (Planned M3) | — |
| `image` | the pinned digest from `deploy --image` (image sources) | `service` |

### 2.3 `[secrets.<name>]` and `[app_env]`

`[secrets.<name>]`: `generate = "alnum32"` (32 characters `[A-Za-z0-9]`, generated once at `init`, pairwise distinct per instance), `mode` (file mode, default `"0400"`). The file is `<secrets_dir>/<name>`; the Compose file references it through the `secrets_dir` param.

`[app_env]` describes an `env_file` that Ingat renders from the instance's `[app_env]` values and secrets:

| Key | Meaning |
|---|---|
| `param` | The `env_file` param the Compose file uses |
| `forbidden` | Keys the image fixes and no instance may set (they would redirect data or change runtime identity) |
| `[app_env.keys] <KEY>` | `required`, `default`, `allowed` (list), `pattern`, `secret` (value set with `ingat secret set`, stored in `secrets/env/<KEY>`), `owner_gated` (a change makes the plan class D; dropped from isolated runs), `tool_managed` (set only by holds and `[rollback] env`) |

Undeclared keys in the instance's `[app_env]` are refused. Values are rendered single-quoted; a value containing `'`, a newline or NUL is refused.

### 2.4 `[stores.<name>]` and `[services]`

| Store key | Meaning |
|---|---|
| `kind` | `"volume"` (a top-level Compose volume) or `"bind"` (a host directory) |
| `volume` | Compose volume key (`kind = "volume"`) |
| `param` | `store` param used as the bind source (`kind = "bind"`) |
| `service` | The data service that serves this store (optional for bind stores used by writers directly) |
| `ready` | Probe that proves the store is ready (required when `service` is set) |
| `owner`, `mode` | Owner `uid:gid` and mode of new bind generations |
| `local_only` | Refuse a generation path that is not a local filesystem |
| `online_backup` | The app's backup tasks are consistent while writers run, so scheduled and manual backups keep writers up (pre-change and final bundles always stop writers) |

Every named volume in the merged model must be a store. `[services]`: `data` (started first; never recreated by a code-only change), `writers` (stopped for every data-changing step), `stateless`, `log_snapshot` (services whose bounded logs are saved before a recreate or stop). Every long-running service outside Compose profiles must have exactly one role; services inside Compose profiles are task-only.

### 2.5 `[schema]`

`task` (a read task printing JSON) or `probe` (a probe whose JSON has the fields), plus `expected` and `actual` (dotted JSON paths), and `migrates_on_start` (bool). Recorded in every deployment and bundle; used by the rollback gate and by `observe = "schema"`. When it is read: a task-based schema runs as a scratch step before every bundle capture and before `start`; a probe-based schema is recorded with its time when the probe passes at activation, and bundles use that recorded value (a running app's schema changes only through a deploy). The `start` check does not apply to a probe-based `migrates_on_start` app (`LIFECYCLE.md` §4.7, §4.11).

### 2.6 Activation, smoke, install, deploy

- `[[activate]]`: ordered groups `{services, wait = [probe…], reopens_writes}`. Exactly one group has `reopens_writes = true` when writers exist; it is the second forward point and records `writes_reopened_at`.
- `[[smoke]]`: read-only `http` probes run after every activation on the live instance (§5).
- `[[install]]`: first-install steps, each one of `{start = [services], wait, params, log_snapshot}`, `{task = "<name>"}`, `{pause = "<text>", allow_tasks = [...]}`.
- `[deploy]`: `prechecks` (read tasks run before the freeze, each on the image set its task declares, `current` or `candidate`; each must be `ok`), `migrate` (task), `postchecks` (read tasks after migrate, normally on the candidate; each must be `ok`), `baseline` (**Planned M3**: read tasks on the current images, recorded with findings allowed, the input of a comparison postcheck; no M2 consumer uses it).

### 2.7 Backup, restore, rollback, drill

| Table | Keys |
|---|---|
| `[backup]` | `strategy = "tasks" \| "none"`, `steps` (tasks in order), `verify` (tasks), `payload` (required top-level entry name; templated), `[backup.naming]` (per class `scheduled`, `manual`, `pre-change`, `final`; default `"{bundle.stamp}-{class}"`) |
| `[restore]` | `start` (data services started on the new generation), `steps`, `post`, `checks` (tasks that must be `ok`), `activate` (start the activation groups in isolation and wait for `exec`/`health` probes). Restore tasks always run in the bundle's own release image (`LIFECYCLE.md` §4.10). |
| `[rollback]` | `env` (env overrides for a restore-based rollback deployment; dropped by the next deploy) |
| `[drill]` | `checks` (must be `ok`), `record` (recorded, findings allowed), `activate`, `min_free_memory`. Drills always use throwaway secrets. |
| `[holds.<service>]` | env overrides applied in every isolated run: side-effect holds, and values a service needs to start in isolation (internal networks have no default route) |
| `[side_effects]` | `kind = "none" \| "outbound"`, `restore_via_app`, `after_restore = "held"`, `clear_hold` (task), `single_active` (Planned M4), `restore_notice` |

## 3. Template vocabulary (closed)

| Variable | Value | Contexts |
|---|---|---|
| `{instance}`, `{environment}`, `{host}` | instance name, environment label, host name | all |
| `{operator}`, `{reason}`, `{op.seq}` | `SUDO_USER` or `root`, the `--reason` text (or `scheduled <class> backup`), operation sequence | all task argv |
| `{release}`, `{commit}` | release (tag or commit) and 40-hex commit of the image set **this invocation runs** | all |
| `{target.release}` | the release a deploy, rollback or restore moves to | deploy, restore, naming |
| `{image.<service>}` | image ID (`sha256:…`) of that service in the image set this invocation runs; for an imported adoption payload, the bundle's recorded deployment, which is the prepared candidate (`LIFECYCLE.md` §4.16) | task argv |
| `{schema.expected}` | from this operation's schema read (task-based `[schema]`), or the value the deployment record holds from its activation (probe-based) (`LIFECYCLE.md` §4.7) | backup task argv |
| `{bundle.id}`, `{bundle.payload}` | bundle id; its single payload entry | backup, verify, restore, migrate |
| `{bundle.stamp}` | bundle creation time `YYYYMMDDTHHMMSSZ` (UTC) | naming |
| `{class}` | bundle class | naming |
| `{freeze_at}` | writer stop time `YYYY-MM-DDTHH:MM:SSZ` (UTC, seconds) | deploy migrate |
| `{param.<NAME>}` | a declared param's value | all |
| `{arg.<name>}` | a typed task argument | that task |
| `{input.<name>}` | the file name of an `inbox/` input | that task |

Unknown variables, or a variable outside its context, are validation errors. There are no expressions. Rendered values are checked for NUL and newlines and are only ever argv elements or env values, never shell text.

## 4. Tasks `[tasks.<name>]`

| Key | Values | Meaning |
|---|---|---|
| `service` | Compose service | The container image, user, networks, env and mounts the task inherits |
| `mode` | `"run"` \| `"exec"` | `run`: `compose run --rm --no-deps -T --name <instance>-x<seq>-<step>-a<attempt>` with op labels (no `-T` for `stdin = "terminal"`); `argv` replaces the service command (the entrypoint stays). `exec`: inside the running service container; `argv` is the full command. |
| `image` | `"current"` (default) \| `"candidate"` \| `"bundle"` | Which recorded image set the invocation pins |
| `argv` | list of templates | Arguments |
| `env` | table | Extra env (templated) |
| `user` | `"uid:gid"` | Overrides the image user; also the owner of stages and input copies |
| `stdin` | `"file:<stage path>"` \| `"bundle:<path in payload>"` \| `"terminal"` | `file:` and `bundle:` are streamed byte-exact by Ingat; `terminal` attaches the CLI's TTY (the command refuses without one) so a prompt can turn echo off |
| `stdout` | `"json"` \| `"record"` \| `"terminal"` \| `"file:<stage path>"` | `terminal` is never captured; `record` is stored 0600; `json` and `record` are text captures (bounded, redacted); `file:` is byte-exact, never redacted or truncated |
| `nonempty` | bool | A `file:` stdout must not be empty |
| `mounts` | table target → source | Target is a container path (`compose run -v`) or a `task_dir`/`store` param name. Sources: `"stage"` (the writable stage directory; `file:` stdin/stdout paths are relative to it), `"bundle"` (a private read-only copy of the operation's bundle `payload/` directory, owned by the task user; the payload entry is its single child), `"generation:<store>"` (the new generation; that store's own param is bound to `placeholder/` for this invocation), `"input:<name>"` (a private read-only directory holding one copied `inbox/` file; `{input.<name>}` is its file name) |
| `effect` | `"read"` \| `"app-write"` \| `"data"` | Effect on instance data |
| `idempotent` | bool | Safe to re-run after an unknown outcome |
| `observe` | `"schema"` | How an unknown outcome is decided |
| `exit` | table code → `ok` \| `finding` \| `refused` \| `failed` \| `unknown` | Undeclared non-zero: `failed` for `read`, `unknown` otherwise |
| `expect` | `{json = {<dotted path> = value or [any-of…]}}` (the probe grammar of §5, JSON only) | Must hold on the parsed `json` or `record` stdout for an `ok` exit to count as `ok`; otherwise the outcome is `failed` (read) or `unknown` (write). Used where one exit code means two things (the SQLite consumer's outbound preview command exits 2 both for a preview and for a usage error; §11). |
| `args` | table name → regex | Typed arguments (`--arg name=value`) |
| `clears_hold` | bool | Success clears `held_since` |
| `operator` | bool (default `true`) | `false`: only operations may run it |
| `max_input_bytes` | int | Limit for `input:` files |
| `timeout` | duration | Hard limit; the task container is stopped and the step becomes `unknown` (data effect) or `failed` (read) |

Validation rules specific to tasks: a task with effect `app-write` or `data` in `exec` mode may only appear in `restore.steps` or `restore.post` (isolated projects only: safety floor F15, `LIFECYCLE.md` §1); tasks used as `deploy.migrate` or in `[[install]]` with effect `data` must be `idempotent` or declare `observe`; every task in `backup.steps` or `backup.verify` is scratch class whatever its effect, may write only into the stage and the app's own backup bookkeeping, and must be `idempotent = true` unless its effect is `read` (`LIFECYCLE.md` §3.3); a task with `stdin` or `stdout = "terminal"` runs in the foreground CLI and may not be used by `scheduled`; `expect` requires `stdout = "json"` or `"record"`.

## 5. Probes `[probes.<name>]` and `[[smoke]]`

| Kind key | Runs | Allowed in isolated runs |
|---|---|---|
| `health = "<service>"` | the container's Docker health status must be `healthy` | yes |
| `exec = "<service>"` with `argv` | inside the running container; exit 0 required (or `expect.exit`), stdout optionally parsed as JSON | yes |
| `http = {port_param, path, method = "GET", headers = {}, body}` | from the Ingat container over host loopback to `127.0.0.1:<port>` (the wrapper uses `--network host`) | no: recorded as not applicable |

Common keys: `expect` = `{status, json = {<dotted path> = value or [any-of…]}, body_contains, header_equals = {<header> = exact value}, header_contains = {<header> = substring}, exit}`, `stable` (the probe must pass continuously for this long; default `0s`), `interval` (default `2s`), `timeout` (default `60s`). Probes never create containers, so `status` and `check` keep the no-trace rule (`exec` events of declared read-only probes are the only Docker events allowed). Every `[[smoke]]` entry is an `http` probe plus a `name`; the image identity check (each running container's image ID equals the recorded ID) is built in and always runs.

## 6. Instance config schema 1

### 6.1 Keys

| Key | Meaning |
|---|---|
| `instance = 1` | Schema version |
| `name` | `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, at most 30 characters; the Compose project name; `--` cannot occur |
| `app`, `environment` | App id (must equal the manifest's `app`); environment label `^[a-z][a-z0-9-]{0,31}$` |
| `disposable` | Fixed at `init`; lets purge skip its restore-test (the confirmation screen says so). It never relaxes approval: class D stays terminal-only. |
| `[source]` | git: `repo` (ssh or https URL), `key` (name of a deploy key in `INGAT_ROOT/keys/`), `manifest` (path, default `ingat.toml`), `accept` (optional regex narrowing allowed refs). Image apps: `kind = "image"`. |
| `[params]` | Values for declared params only; `port` and `subnet` may be fixed here or left to allocation |
| `[app_env]` | Values for declared non-secret app-env keys |
| `[backups]` | `keep_daily`, `keep_weekly`, `keep_monthly`, `pin_pre_change_days`, `max_age_hours` (status attention), `restore_test_max_age_days` |
| `[monitor]` | **Planned M3:** `public_url`, `cert_warn_days`, `resolve_to`, `ca_file` |

### 6.2 Validation (`ingat validate <repo-dir> [--instance <file>]`, offline, also in app CI)

1. Strict parse of both files; schema versions; `requires_ingat` satisfied.
2. Compose files exist; `compose config --variables` shows every variable without a default declared, and every declared param used.
3. The merged runtime model, every task model and the isolated model render with sample values and pass the policy (`ARCHITECTURE.md` §9.5).
4. Every named volume is a store; every bind store's param is a bind source; every published port comes from a `port` param on `127.0.0.1`.
5. Every long-running service has one role; writers exist when stores exist; activation covers every long-running service; exactly one `reopens_writes` group when writers exist.
6. Every referenced task, probe and service exists; exit maps are valid; template variables are in the closed set and in context; the task rules of §4 hold.
7. `[app_env]` param is an `env_file` param; no forbidden key is declared; Compose file secrets map to `[secrets.*]` through the `secrets_dir` param.
8. `side_effects.kind = "outbound"` requires holds, a restore task and `restore_via_app = true`.

## 7. Fixtures behind the examples

The examples are written as a consumer's own repository manifest would be, with the CI fixtures' names (`ARCHITECTURE.md` §10.2); each real consumer keeps its `ingat.toml` in its own repository. Each fixture reproduces the app behaviour its example depends on:

- **`fx-pg`** mirrors the PostgreSQL consumer (§8-§10). Long-running services: `db` (`postgres:16`, the data service), `backend` (the writer; its image has no entrypoint, runs as uid `10001` and carries the OCI version and revision labels) and `web` (stateless; it keeps serving the current shell while `backend` is stopped). Task-only services in Compose profile `ops`: `migrate` (its entrypoint is the app's migrate command), `status` (its entrypoint is the app's status report), and `db-roles` and `backup-tools` (their entrypoint is the app CLI). File secrets come from a bind-mounted secrets directory, one port is published through the edge, the edge network has a fixed subnet, and every service has memory and `cpus` params. The app CLI exits 0 (ok or clean), 1 (finding or refused) and 2 (could not run, or unknown outcome for a write). Its invariant check `fx-pg check` has a full form and named subsets (`--only setup`, `--only compat`). The readiness endpoint answers 200 only when the release matches and the schema is current; a release write gate answers 409 to a write without the current release header; unknown API paths answer a JSON 404. `migrate` verifies a pre-change backup taken after the freeze (`--not-before`), and the app's backup names use a UTC stamp. Dumps carry no grants, so a restore re-provisions roles and grants. The postgres image's temporary init server listens only on the socket, so readiness is a stable TCP probe. `web` derives its proxy address from the default IPv4 route and refuses to start without one unless the address is set; internal networks have no default route.
- **`fx-lite`** mirrors the SQLite consumer (§11, §12). One container (`app`) holds the web app, an in-process job runner and the SQLite database (WAL) in a bind-mounted data directory owned by `10001:10001`. It migrates at start and also has explicit `migrate`, online `backup --to` (outside the data directory), `restore --from … --to` (verifies hashes, integrity and schema, then sets the outbound pause with reason `restored` and holds queued sends) and `bootstrap` commands. Its outbound mail queue is gated by an owner-controlled delivery mode; its preview-then-confirm outbound commands run the app's migration first and exit 2 both for a preview and for a usage error. Its readiness JSON reports `status`, `data_writable` and `schema.expected`/`schema.actual`.
- **`fx-web`** is the stateless site of §13.

## 8. Example: `fx-pg` app manifest (the PostgreSQL consumer pattern; one file serves staging and production)

```toml
# ingat.toml — fx-pg app manifest (Ingat manifest schema 1). Ingat reads it from the exact commit it deploys.
manifest = 1
app = "fx-pg"
requires_ingat = ">=0.1,<1"
# The app's own rule: no other instance of it on a daemon that runs production (§10).
exclusive_environments = ["production"]

[source]
kind = "git"
release = "tag"
tag_pattern = '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(alpha|beta|rc)\.[1-9][0-9]*)?$'

[compose]
files = ["compose.yaml"]
build_files = ["compose.yaml", "compose.build.yaml"]
build_services = ["backend", "web"]
build_env = { FXPG_RELEASE = "{release}", FXPG_COMMIT = "{commit}" }
expect_labels = { "org.opencontainers.image.version" = "{release}", "org.opencontainers.image.revision" = "{commit}" }

[params]
FXPG_RELEASE         = { kind = "template", value = "{release}" }
FXPG_SECRETS_DIR     = { kind = "secrets_dir" }
FXPG_BACKUP_DIR      = { kind = "task_dir" }
FXPG_ACCEPT_SCHEMA   = { kind = "accept_schema" }
FXPG_HTTP_PORT       = { kind = "port" }
FXPG_EDGE_SUBNET     = { kind = "subnet" }
FXPG_TIMEZONE        = { required = true, pattern = '^[A-Za-z]+(/[A-Za-z0-9_+-]+)+$' }
POSTGRES_USER        = { default = "fx_owner", pattern = '^[a-z_][a-z0-9_]{0,62}$' }
POSTGRES_DB          = { default = "fx", pattern = '^[a-z_][a-z0-9_]{0,62}$' }
FXPG_BACKEND_WORKERS = { default = "2", pattern = '^[1-8]$' }
FXPG_PROXY_ADDRESS   = { default = "", pattern = '^([0-9.]+(/[0-9]{1,2})?)?$' }
FXPG_DB_MEMORY       = { optional = true, pattern = '^[0-9]+[mg]$' }
FXPG_DB_CPUS         = { optional = true, pattern = '^[0-9]+(\.[0-9]+)?$' }
FXPG_BACKEND_MEMORY  = { optional = true, pattern = '^[0-9]+[mg]$' }
FXPG_BACKEND_CPUS    = { optional = true, pattern = '^[0-9]+(\.[0-9]+)?$' }
FXPG_WEB_MEMORY      = { optional = true, pattern = '^[0-9]+[mg]$' }
FXPG_WEB_CPUS        = { optional = true, pattern = '^[0-9]+(\.[0-9]+)?$' }
FXPG_OPS_MEMORY      = { optional = true, pattern = '^[0-9]+[mg]$' }
FXPG_OPS_CPUS        = { optional = true, pattern = '^[0-9]+(\.[0-9]+)?$' }

[secrets.postgres_password]                 # the postgres image reads it only when it initialises a new data volume
generate = "alnum32"
mode = "0444"                               # read by uid 10001 through the bind mount
[secrets.app_password]
generate = "alnum32"
mode = "0444"
[secrets.maintenance_password]
generate = "alnum32"
mode = "0444"

[stores.pgdata]
kind = "volume"
volume = "postgres_data"
service = "db"
ready = "db-ready"
online_backup = true                        # one pg_dump snapshot is consistent while backend writes

[services]
data = ["db"]
writers = ["backend"]
stateless = ["web"]                         # keeps serving the shell while backend is stopped
log_snapshot = ["db", "backend", "web"]

[schema]
task = "revision"
expected = "expected_revision"
actual = "database_revision"
migrates_on_start = false                   # the backend never migrates; migration is the explicit `migrate` task

# ---------------------------------------------------------------- probes
[probes.db-ready]                           # TCP, not the socket: the image's temporary init server listens only on the socket
exec = "db"
argv = ["pg_isready", "-h", "127.0.0.1", "-p", "5432", "-U", "{param.POSTGRES_USER}", "-d", "{param.POSTGRES_DB}"]
stable = "15s"
timeout = "180s"

[probes.backend-ready]                      # readiness, not liveness: 200 only when the schema is current (or accepted after `rollback --accept-schema`, Planned M3)
exec = "backend"
argv = ["wget", "-q", "-O", "-", "-T", "3", "http://127.0.0.1:8000/api/health"]
expect = { json = { status = "ok", release = "{release}", schema = "current" } }   # "accepted" is added only for `rollback --accept-schema` (M3, ADR)
stable = "5s"
timeout = "180s"

[probes.web-healthy]
health = "web"
timeout = "60s"

[probes.edge-ready]
http = { port_param = "FXPG_HTTP_PORT", path = "/api/health" }
expect = { status = 200, json = { status = "ok", release = "{release}" } }
timeout = "60s"

[[activate]]
services = ["db"]
wait = ["db-ready"]
[[activate]]
services = ["backend"]                      # web still serves the previous bundle; its writes get 409 from the release gate
wait = ["backend-ready"]
[[activate]]
services = ["web"]
wait = ["web-healthy", "edge-ready"]
reopens_writes = true

# ---------------------------------------------------------------- smoke (the image identity check is built in)
[[smoke]]
name = "shell-is-release"
http = { port_param = "FXPG_HTTP_PORT", path = "/" }
expect = { status = 200, header_contains = { "content-type" = "text/html" }, header_equals = { "cache-control" = "no-cache" }, body_contains = '<meta name="fx-release" content="{release}">' }
[[smoke]]
name = "spa-fallback"
http = { port_param = "FXPG_HTTP_PORT", path = "/app/deep/link" }
expect = { status = 200, header_contains = { "content-type" = "text/html" } }
[[smoke]]
name = "ready-on-release"
http = { port_param = "FXPG_HTTP_PORT", path = "/api/health" }
expect = { status = 200, json = { release = "{release}", schema = "current" } }   # "accepted" never passes the smoke
[[smoke]]
name = "live-on-release"
http = { port_param = "FXPG_HTTP_PORT", path = "/api/health/live" }
expect = { status = 200, json = { release = "{release}" } }
[[smoke]]
name = "unknown-api-is-json-404"
http = { port_param = "FXPG_HTTP_PORT", path = "/api/fx-smoke-missing" }
expect = { status = 404, header_contains = { "content-type" = "application/json" } }
[[smoke]]
name = "write-gate-refuses-missing-release"
http = { port_param = "FXPG_HTTP_PORT", method = "POST", path = "/api/fx-smoke-gate", headers = { "X-Fx-CSRF" = "1", "Content-Type" = "application/json" }, body = "{}" }
expect = { status = 409, json = { stale_release = true } }
[[smoke]]
name = "write-gate-passes-current-release"
http = { port_param = "FXPG_HTTP_PORT", method = "POST", path = "/api/fx-smoke-gate", headers = { "X-Fx-CSRF" = "1", "Content-Type" = "application/json", "X-Fx-Release" = "{release}" }, body = "{}" }
expect = { status = 404 }

# ---------------------------------------------------------------- first install
[[install]]
start = ["db"]
wait = ["db-ready"]
[[install]]
task = "db-roles"
[[install]]
task = "migrate-first"
[[install]]
start = ["backend"]
params = { FXPG_BACKEND_WORKERS = "1" }     # first-run setup needs one worker
wait = ["backend-ready"]
log_snapshot = false
[[install]]
start = ["web"]
wait = ["web-healthy", "edge-ready"]
[[install]]
pause = "First-run setup: read the one-time setup code with `ingat logs {instance} backend --since 15m` (it is in the backend log, which anyone who can run `ingat logs` can read, so finish setup now), create the first administrator at the instance URL, then run `ingat resume {instance}`."
[[install]]
start = ["backend"]                         # recreated with the configured worker count
wait = ["backend-ready"]
log_snapshot = false                        # the previous backend log holds the setup code
[[install]]
task = "check-setup"

# ---------------------------------------------------------------- update
[deploy]
baseline = []                               # Planned M3 (owner decision OD-7): ["check"], findings allowed, compared after migrate
prechecks = ["check", "check-compat-candidate"]   # the current image must be clean; the candidate's compatibility subset
migrate = "migrate"
postchecks = ["check-candidate"]            # the full check on the candidate after migrate must be clean; with a baseline, a comparison task replaces it

# ---------------------------------------------------------------- backup (the payload is the app's own backup directory)
[backup]
strategy = "tasks"
steps = ["pg-dump", "pg-list", "pg-revision", "backup-publish"]
verify = ["backup-verify"]
payload = "{bundle.id}"

[backup.naming]                             # the app's own backup name grammar
scheduled = "{bundle.stamp}-daily"
manual = "{bundle.stamp}-manual"
final = "{bundle.stamp}-manual"
pre-change = "{bundle.stamp}-pre-release-{target.release}"

# ---------------------------------------------------------------- restore (into a new generation, in an isolated project)
[restore]
start = ["db"]
steps = ["pg-restore"]
post = ["db-roles", "db-grants"]            # dumps carry no grants
checks = ["revision", "restore-check"]
activate = false

[drill]
checks = ["revision", "restore-check"]
record = ["check"]
activate = true                             # start backend and web in isolation; exec and health probes only
min_free_memory = "2g"                      # a second PostgreSQL runs during the drill

[holds.web]                                 # internal networks have no default route; without this web exits at start
FXPG_PROXY_ADDRESS = "127.0.0.1"            # any IPv4 address works: no proxy traffic exists in isolation

[side_effects]
kind = "none"

# ---------------------------------------------------------------- tasks
[tasks.revision]                            # read-only schema probe; 0 current, 1 any other state, 2 could not run
service = "backend"
mode = "run"
argv = ["fx-pg", "revision"]
effect = "read"
stdout = "json"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "2m"

[tasks.check]                               # full report: deploy precheck (must be clean), drill record, a daily `ingat scheduled task`
service = "backend"
mode = "run"
argv = ["fx-pg", "check", "--max-findings", "10000"]
effect = "read"
stdout = "record"                           # may hold personal data: stored 0600
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "30m"

[tasks.check-setup]                         # after the first install: first-run setup is complete
service = "backend"
mode = "run"
argv = ["fx-pg", "check", "--only", "setup"]
effect = "read"
stdout = "record"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "10m"

[tasks.check-compat-candidate]              # precheck with the candidate image, before the freeze
service = "backend"
mode = "run"
image = "candidate"
argv = ["fx-pg", "check", "--only", "compat"]
effect = "read"
stdout = "record"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "10m"

[tasks.check-candidate]                     # post-migrate check: the full report with the candidate image
service = "backend"
mode = "run"
image = "candidate"
argv = ["fx-pg", "check", "--max-findings", "10000"]
effect = "read"
stdout = "record"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "30m"

[tasks.restore-check]
service = "backend"
mode = "run"
argv = ["fx-pg", "check", "--only", "setup", "--only", "compat"]
effect = "read"
stdout = "record"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "10m"

[tasks.migrate]                             # the service's entrypoint is the app's migrate command
service = "migrate"
mode = "run"
image = "candidate"
argv = ["--pre-change-backup", "{bundle.payload}", "--not-before", "{freeze_at}", "--backup-dir", "/backups"]
mounts = { FXPG_BACKUP_DIR = "bundle" }     # private read-only copy owned by uid 10001
effect = "data"
idempotent = true                           # an at-head database answers already_current
observe = "schema"
stdout = "record"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
operator = false
timeout = "60m"

[tasks.migrate-first]
service = "migrate"
mode = "run"
image = "candidate"
argv = ["--without-backup", "first install: empty database (ingat op {op.seq})"]
effect = "data"
idempotent = true
observe = "schema"
stdout = "record"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
operator = false
timeout = "30m"

[tasks.db-roles]                            # the service's entrypoint is the app CLI; safe to repeat
service = "db-roles"
mode = "run"
argv = ["roles"]
effect = "data"
idempotent = true
stdout = "record"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
timeout = "5m"

[tasks.db-grants]
service = "db-roles"
mode = "run"
argv = ["grants"]
effect = "data"
idempotent = true
stdout = "record"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
timeout = "5m"

[tasks.pg-dump]
service = "db"
mode = "exec"
env = { TZ = "UTC" }                        # the archive stores local-time fields
argv = ["pg_dump", "-U", "{param.POSTGRES_USER}", "-d", "{param.POSTGRES_DB}", "--format=custom", "--no-owner", "--no-privileges", "--lock-wait-timeout=60s"]
stdout = "file:.partial/{bundle.id}/db.dump"
nonempty = true
effect = "read"
exit = { 0 = "ok" }
timeout = "60m"

[tasks.pg-list]
service = "db"
mode = "exec"
env = { TZ = "UTC" }
argv = ["pg_restore", "--list"]
stdin = "file:.partial/{bundle.id}/db.dump"
stdout = "file:.partial/{bundle.id}/db.dump.list"
nonempty = true
effect = "read"
exit = { 0 = "ok" }
timeout = "10m"

[tasks.pg-revision]
service = "db"
mode = "exec"
env = { TZ = "UTC" }
argv = ["pg_restore", "--data-only", "--table=schema_version", "--file=-"]
stdin = "file:.partial/{bundle.id}/db.dump"
stdout = "file:.partial/{bundle.id}/schema_version.sql"
effect = "read"
exit = { 0 = "ok" }
timeout = "10m"

[tasks.backup-publish]                      # publishes <stage>/{bundle.id}/ with the app's own backup manifest and SHA256SUMS
service = "backup-tools"
mode = "run"
argv = ["backup-publish", "--name", "{bundle.id}", "--operator", "{operator}", "--reason", "{reason}",
        "--release-tag", "{release}", "--release-commit", "{commit}", "--expected-revision", "{schema.expected}",
        "--environment", "{environment}", "--host", "{host}",
        "--image-backend", "{image.backend}", "--image-web", "{image.web}", "--image-db", "{image.db}"]
mounts = { FXPG_BACKUP_DIR = "stage" }
effect = "read"                             # writes only into the stage
stdout = "json"
exit = { 0 = "ok", 1 = "refused", 2 = "failed" }
timeout = "10m"

[tasks.backup-verify]
service = "backup-tools"
mode = "run"
argv = ["verify-backup", "{bundle.payload}", "--database", "{param.POSTGRES_DB}"]
mounts = { FXPG_BACKUP_DIR = "bundle" }
effect = "read"
stdout = "json"
exit = { 0 = "ok", 1 = "failed", 2 = "failed" }
timeout = "20m"

[tasks.pg-restore]                          # exec into the isolated project's db only
service = "db"
mode = "exec"
env = { TZ = "UTC" }
argv = ["pg_restore", "--single-transaction", "--exit-on-error", "--no-owner", "--no-privileges", "-U", "{param.POSTGRES_USER}", "-d", "{param.POSTGRES_DB}"]
stdin = "bundle:{bundle.payload}/db.dump"
effect = "data"
exit = { 0 = "ok" }
operator = false
timeout = "120m"

[tasks.app-status]                          # read-only report; its backup-age field is not authoritative under Ingat
service = "status"
mode = "run"
argv = []
effect = "read"
stdout = "json"
exit = { 0 = "ok", 1 = "finding", 2 = "failed" }
timeout = "2m"

[tasks.reset-password]                      # recovery; the password is typed at the prompt, never an argument
service = "backend"
mode = "run"
argv = ["fx-pg", "reset-password", "--user", "{arg.user}"]
args = { user = '^[A-Za-z0-9._@-]{1,64}$' }
stdin = "terminal"
stdout = "terminal"
effect = "app-write"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
timeout = "5m"

[tasks.recover-admin-role]                  # recovery; a free-text name without control characters
service = "backend"
mode = "run"
argv = ["fx-pg", "recover-admin-role", "--role-name", "{arg.role_name}"]
args = { role_name = '^[^\x00-\x1f]{1,100}$' }
stdout = "terminal"
effect = "app-write"
exit = { 0 = "ok", 1 = "refused", 2 = "unknown" }
timeout = "5m"
```

## 9. Example: `fx-pg` staging instance (`INGAT_ROOT/instances/pg-staging/instance.toml`)

```toml
instance = 1
name = "pg-staging"
app = "fx-pg"
environment = "staging"
disposable = true                     # synthetic data only; fixed at init; purge may skip its restore-test

[source]
repo = "ssh://git@github.com/<owner>/<app>.git"
key = "fx-pg"                         # INGAT_ROOT/keys/fx-pg/ (read-only deploy key, pinned known_hosts)
accept = '^v[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|rc)\.[1-9][0-9]*)?$'

[params]
FXPG_TIMEZONE = "Etc/UTC"             # example value; the same as production
FXPG_HTTP_PORT = "20081"              # fixed: the host's reverse proxy points here
FXPG_EDGE_SUBNET = "10.200.1.0/24"
FXPG_BACKEND_WORKERS = "2"
FXPG_DB_MEMORY = "512m"
# Required on a host without CPU CFS quota (as on DSM 7.4.1 with Container Manager 24.0.2-1706): the capability check refuses any non-zero `cpus`.
FXPG_DB_CPUS = "0"
FXPG_BACKEND_CPUS = "0"
FXPG_WEB_CPUS = "0"
FXPG_OPS_CPUS = "0"

[backups]
keep_daily = 7
keep_weekly = 4
keep_monthly = 0
pin_pre_change_days = 14
max_age_hours = 26
restore_test_max_age_days = 8
```

Staging runs the same runtime Compose files as production, not a separate development Compose file, so it exercises exactly what production will run; an app that sets secure session cookies therefore needs HTTPS in front of staging too. `disposable` never lets an agent run class D on it: purge and restore over staging stay terminal-only (owner decision OD-10).

## 10. Example: `fx-pg` production instance (`INGAT_ROOT/instances/pg-prod/instance.toml`)

Created only after owner decision OD-5 is decided (the manifest's `exclusive_environments` refuses it while `pg-staging` is registered on the same host).

```toml
instance = 1
name = "pg-prod"
app = "fx-pg"
environment = "production"
disposable = false

[source]
repo = "ssh://git@github.com/<owner>/<app>.git"
key = "fx-pg"
accept = '^v[0-9]+\.[0-9]+\.[0-9]+$'          # final tags only

[params]
FXPG_TIMEZONE = "Etc/UTC"
FXPG_HTTP_PORT = "20080"
FXPG_EDGE_SUBNET = "10.200.0.0/24"
FXPG_BACKEND_WORKERS = "2"
# On a host without CPU CFS quota, as in §9; a host with CPU CFS support may set real limits:
FXPG_DB_CPUS = "0"
FXPG_BACKEND_CPUS = "0"
FXPG_WEB_CPUS = "0"
FXPG_OPS_CPUS = "0"

[backups]
keep_daily = 14
keep_weekly = 8
keep_monthly = 12
pin_pre_change_days = 30                      # pre-change bundles stay through the observation window
max_age_hours = 26
restore_test_max_age_days = 8

# [monitor]                                   # Planned M3
# public_url = "https://<public host>/"
# cert_warn_days = 21
# resolve_to = "127.0.0.1"
```

## 11. Example: `fx-lite` app manifest (the SQLite consumer pattern)

This is the M2 acceptance form: a runtime Compose file whose network takes a fixed subnet from a `subnet` param, plus a build file that adds `build: .`. The M1 form mirrors the SQLite consumer before it has that runtime file: `files` and `build_files` are one Compose file that also carries `build: .` (the generated override resets it; `up` never builds) and there is no `FXLITE_SUBNET` param; everything else is identical.

```toml
# ingat.toml — fx-lite app manifest (Ingat manifest schema 1).
manifest = 1
app = "fx-lite"
requires_ingat = ">=0.1,<1"

[source]
kind = "git"
release = "commit"                            # one image tag per release commit

[compose]
files = ["compose.yaml"]                      # the service without `build:`; network subnet from FXLITE_SUBNET
build_files = ["compose.yaml", "compose.build.yaml"]
build_services = ["app"]
build_env = { FXLITE_IMAGE = "fx-lite:{commit}" }

[params]
FXLITE_IMAGE    = { kind = "template", value = "fx-lite:{commit}" }
FXLITE_ENV_FILE = { kind = "env_file" }
FXLITE_DATA_DIR = { kind = "store", store = "data" }
FXLITE_PORT     = { kind = "port" }
FXLITE_SUBNET   = { kind = "subnet" }         # a stable gateway, so PROXY_ADDRESS survives a network recreate

[app_env]
param = "FXLITE_ENV_FILE"
# Fixed by the image, or used only by a development seed command that never runs in production.
# Any other undeclared key is refused anyway.
forbidden = ["APP_ENV", "HOST", "PORT", "DATA_DIR", "DATABASE_PATH", "SEED_PASSWORD"]

[app_env.keys]
ALLOWED_ORIGINS  = { required = true }
BASE_URL         = { required = true }
MAIL_SENDER      = { required = true }
PROXY_ADDRESS    = { required = true }
SECURE_COOKIES   = { allowed = ["true", "false"] }
SESSION_HOURS    = { pattern = '^[0-9]{1,4}$' }
DELIVERY_MODE    = { default = "capture", allowed = ["capture", "smtp"], owner_gated = true }
DELIVERY_ENABLED = { allowed = ["true"], owner_gated = true }   # real sending needs both owner-gated keys
MAIL_HOST        = { pattern = '^[A-Za-z0-9.-]{1,253}$' }
MAIL_PORT        = { pattern = '^[0-9]{1,5}$' }
MAIL_SECURITY    = { allowed = ["starttls", "tls"] }
MAIL_USER        = { secret = true }
MAIL_PASSWORD    = { secret = true }
JOBS             = { allowed = ["off"], tool_managed = true }

[stores.data]
kind = "bind"
param = "FXLITE_DATA_DIR"
owner = "10001:10001"                         # the image user
mode = "0700"
local_only = true                             # SQLite WAL: never SMB/NFS or a synchronized folder
online_backup = true                          # SQLite online backup

[services]
writers = ["app"]                             # web app, in-process job runner and the SQLite store in one container
log_snapshot = ["app"]                        # honoured from M2

[schema]
probe = "ready"
expected = "schema.expected"
actual = "schema.actual"
migrates_on_start = true                      # every image change is data-changing

[probes.ready]
exec = "app"
argv = ["wget", "-q", "-O", "-", "-T", "4", "http://127.0.0.1:3000/api/ready"]
expect = { json = { status = "ready", data_writable = true } }
stable = "5s"
timeout = "120s"

[probes.edge-live]
http = { port_param = "FXLITE_PORT", path = "/api/health" }
expect = { status = 200, json = { status = "ok" } }
timeout = "30s"

[[activate]]
services = ["app"]
wait = ["ready", "edge-live"]
reopens_writes = true

[[smoke]]
name = "live"
http = { port_param = "FXLITE_PORT", path = "/api/health" }
expect = { status = 200, json = { status = "ok" } }
[[smoke]]
name = "ready"
http = { port_param = "FXLITE_PORT", path = "/api/ready" }
expect = { status = 200, json = { status = "ready", data_writable = true } }

[[install]]
task = "migrate"                              # once and alone: concurrent first opens can fail with SQLITE_BUSY
[[install]]
start = ["app"]
wait = ["ready", "edge-live"]
[[install]]
pause = "Copy the bootstrap file into the Ingat inbox (INGAT_ROOT/inbox/), run `ingat task {instance} bootstrap-config --input config=<file>` (it prints a single-use setup code to the terminal that runs it and never records it), complete setup in the browser, then run `ingat resume {instance}`."
allow_tasks = ["bootstrap-config", "bootstrap-new-code"]

[deploy]
baseline = []
prechecks = []
migrate = "migrate"                           # explicit one-off before the start, so the start applies nothing
postchecks = []

[backup]
strategy = "tasks"
steps = ["backup"]
verify = []                                   # hash-only until the app has a read-only verify command

[restore]
start = []
steps = ["restore"]
post = []
checks = []
activate = true                               # start the app on the new generation in isolation and wait for `ready`

[rollback]
env = { JOBS = "off" }                        # a schema older than the outbound pause cannot hold paused jobs

[drill]                                       # throwaway secrets; mail credentials and owner-gated keys are dropped in isolation
checks = []
record = []
activate = true
min_free_memory = "512m"

[holds.app]
DELIVERY_MODE = "capture"
JOBS = "off"

[side_effects]
kind = "outbound"
restore_via_app = true
after_restore = "held"
clear_hold = "queue-resume"
single_active = true                          # Planned M4: never two queues on one data lineage
restore_notice = "Outbound delivery is paused (reason: restored) and queued sends are held. List them with `ingat task {instance} queue-held`, check the mailbox, then use queue-release-job / queue-release-all / queue-drop-job, check `ingat task {instance} queue-status`, and finally run queue-resume."

# ---------------------------------------------------------------- tasks (all `run`: a second SQLite process is safe under WAL)
[tasks.migrate]
service = "app"
mode = "run"
image = "candidate"
argv = ["fx-lite", "migrate"]
effect = "data"
idempotent = true                             # exclusive lock, one transaction; a re-run applies nothing
exit = { 0 = "ok" }                           # any other exit is unknown (data effect)
operator = false
timeout = "15m"

[tasks.backup]
service = "app"
mode = "run"
argv = ["fx-lite", "backup", "--to", "/out"]
mounts = { "/out" = "stage" }                 # outside the data directory, as the app requires
effect = "app-write"                          # records its outcome in the app's own backup bookkeeping; scratch as a backup step (LIFECYCLE §3.3)
idempotent = true                             # required for a non-read backup task; a redo writes into a fresh stage
stdout = "json"
exit = { 0 = "ok", 1 = "failed", 2 = "refused" }
timeout = "60m"

[tasks.restore]                               # runs only in the isolated project: internal network, read-only root
service = "app"
mode = "run"
image = "bundle"
argv = ["fx-lite", "restore", "--from", "/in/{bundle.payload}", "--to", "/restore"]
mounts = { "/in" = "bundle", "/restore" = "generation:data" }
effect = "data"
exit = { 0 = "ok", 1 = "failed", 2 = "refused" }
operator = false
timeout = "60m"

[tasks.bootstrap-config]
service = "app"
mode = "run"
argv = ["fx-lite", "bootstrap", "--config", "/in/{input.config}"]
mounts = { "/in" = "input:config" }
max_input_bytes = 262144
stdout = "terminal"                           # prints the single-use setup code; never recorded
effect = "app-write"
exit = { 0 = "ok", 1 = "refused", 2 = "refused" }
timeout = "5m"

[tasks.bootstrap-new-code]
service = "app"
mode = "run"
argv = ["fx-lite", "bootstrap", "--new-code"]
stdout = "terminal"
effect = "app-write"
exit = { 0 = "ok", 1 = "refused", 2 = "refused" }
timeout = "2m"

# Outbound reconciliation: the app's own preview (no --confirm; exit 2 with outcome "preview") and its
# confirm commands (--confirm last) are separate tasks. The preview runs the app's migration first and exits 2 for a
# usage error too, so the preview tasks are app-write and idempotent, and `expect` tells a preview from a usage error.
# A read-only preview in the app would make them read tasks (class B).
[tasks.queue-held]                            # lists held jobs: ids, kinds, attempts, blockers; no personal data
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "release"]
effect = "app-write"
idempotent = true
stdout = "record"
expect = { json = { outcome = "preview" } }
exit = { 2 = "ok" }
timeout = "2m"

[tasks.queue-status]                          # the pause and the counts `queue-resume` would release
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "resume"]
effect = "app-write"
idempotent = true
stdout = "record"
expect = { json = { outcome = "preview" } }
exit = { 2 = "ok" }
timeout = "2m"

[tasks.queue-release-job]
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "release", "--job", "{arg.job}", "--confirm"]
args = { job = '^[A-Za-z0-9-]{1,64}$' }
effect = "app-write"
stdout = "record"
exit = { 0 = "ok", 1 = "refused" }
timeout = "2m"

[tasks.queue-release-all]
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "release", "--all", "--confirm"]
effect = "app-write"
stdout = "record"
exit = { 0 = "ok", 1 = "refused" }
timeout = "2m"

[tasks.queue-drop-job]
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "drop", "--job", "{arg.job}", "--confirm"]
args = { job = '^[A-Za-z0-9-]{1,64}$' }
effect = "app-write"
stdout = "record"
exit = { 0 = "ok", 1 = "refused" }
timeout = "2m"

[tasks.queue-resume]
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "resume", "--confirm"]
clears_hold = true
effect = "app-write"
stdout = "record"
exit = { 0 = "ok", 1 = "refused" }            # 1: an attempt still awaits its decision
timeout = "2m"
```

## 12. Example: `fx-lite` test instance (`INGAT_ROOT/instances/lite-test/instance.toml`)

```toml
instance = 1
name = "lite-test"
app = "fx-lite"
environment = "test"
disposable = false                            # keep the restore-tested purge gate even for a test instance

[source]
repo = "ssh://git@github.com/<owner>/<app>.git"
key = "fx-lite"

[params]
FXLITE_PORT = "20090"
FXLITE_SUBNET = "10.200.2.0/24"               # M2 form; in the M1 form the default network keeps Docker's own subnet

[app_env]
ALLOWED_ORIGINS = "https://lite-test.<lan-domain>"
BASE_URL = "https://lite-test.<lan-domain>"
MAIL_SENDER = "lite-test@<domain>"
PROXY_ADDRESS = "10.200.2.1"                  # the subnet's gateway; `ingat doctor lite-test` compares it with the observed proxy peer
DELIVERY_MODE = "capture"                     # owner-gated; `smtp` also needs DELIVERY_ENABLED (class D)

[backups]
keep_daily = 7                                # retention defaults pending owner decision OD-8
keep_weekly = 4
keep_monthly = 6
pin_pre_change_days = 30
max_age_hours = 26
restore_test_max_age_days = 8
```

In the M1 form (no `FXLITE_SUBNET`), `PROXY_ADDRESS` is set to the peer address `ingat doctor lite-test` reports after the first install, followed by a config-only redeploy; that address holds only while the default network is not recreated, which is why the fixed-subnet runtime Compose file is required before the M2 freeze.

A later production instance of the same app differs only in `name`, `environment = "production"`, its URLs and port, and the owner's class D change that sets `DELIVERY_MODE = "smtp"` with `DELIVERY_ENABLED = "true"` after `ingat secret set <i> MAIL_USER` and `MAIL_PASSWORD`.

## 13. Example: generic stateless site (the `fx-web` pattern; files in `INGAT_ROOT/instances/site/app/`)

`ingat.toml`:

```toml
manifest = 1
app = "site"
requires_ingat = ">=0.1,<1"

[source]
kind = "image"
images = { site = "SITE_IMAGE" }

[compose]
files = ["compose.yaml"]

[params]
SITE_IMAGE = { kind = "image", service = "site" }
SITE_PORT  = { kind = "port" }

[services]
stateless = ["site"]

[probes.ready]
http = { port_param = "SITE_PORT", path = "/" }
expect = { status = 200 }
timeout = "60s"

[[activate]]
services = ["site"]
wait = ["ready"]

[backup]
strategy = "none"                             # backup, verify, restore and drill report "not applicable"

[side_effects]
kind = "none"
```

`compose.yaml`:

```yaml
services:
  site:
    image: ${SITE_IMAGE:?}
    ports: ["127.0.0.1:${SITE_PORT:?}:8080"]
    read_only: true
    restart: unless-stopped
    logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}
```

`instance.toml`: `instance = 1`, `name = "site"`, `app = "site"`, `environment = "production"`, `disposable = true`, `[source] kind = "image"`, `[params] SITE_PORT = "20100"`. Deploy with `ingat deploy site --image site=ghcr.io/<owner>/<image>@sha256:<digest>`; rollback is the previous digest.
