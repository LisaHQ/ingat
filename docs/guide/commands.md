# Ingat commands

**English** · [Tiếng Việt](commands.vi.md)

When there is something to do next, the last line, `next:`, names the command to run. Reading, backups and checks never ask for approval. A change asks you to type the instance name (for example `lite-test`); a scheduled job can never approve a change, so it refuses instead. Add `--json` to any command for one block of machine-readable output. Everyday tasks, with examples, are in the [operator guide](operator-guide.md#5-everyday-tasks).

## All commands in version 0.1.0 (milestone M1)

Run as root. Approval classes: A reads only, B only adds things (backups, checks) or removes what your keep rules allow, C changes something and asks you to type the instance name (for `host init`, the name that the `hostname` command prints) on a terminal ([`docs/design/LIFECYCLE.md`](../design/LIFECYCLE.md#2-approval-classes-and-commands) §2). Exit codes are in [§6](../design/LIFECYCLE.md#6-exit-codes-every-command). The paths that `init --config` and `validate` take must be full paths inside one of Ingat's two folders.

| Command | What it does |
|---|---|
| `version` | Versions of the tool, the `ingat` command and the image |
| `host init`, `host check` | Link Ingat's folder to this Docker engine and record its facts (class C); record the facts and risks as a host check |
| `init <i> --config <file> --ref <ref>` | Register an instance from its `instance.toml` (class C) |
| `validate <repo-dir> [--instance <file>]` | Check an app repository, and optionally an instance file, without changing anything |
| `prepare <i> <ref>` | Fetch that version, download its images and pin them (class B) |
| `deploy <i> <ref>` | First install, update that changes data, update that changes only settings, or the way forward after a stopped update (class C); prepares first when needed |
| `start\|stop\|restart <i> [<service>…]` | Start, stop or restart the recorded deployment (class C) |
| `task <i> <task> [--arg NAME=VALUE]… [--input NAME=FILE]…` | Run a task the app declares (class B when it only reads, else C); `--input` names a file in `INGAT_ROOT/inbox/` |
| `backup <i> [--class <class>] [--reason TEXT] [--prune]` | Make a sealed, checked backup copy (class B; `--class` defaults to `manual`) |
| `verify <i> <bundle>\|--latest [--restore-test]` | Check a backup copy again; `--restore-test` also test-restores it (class B) |
| `prune <i> --bundles [--apply]` | Remove old backup copies by the keep rules: a dry run, or the removal with `--apply` (class B) |
| `resume <i>`, `abandon <i>` | Continue the unfinished operation, or undo what can be undone and close it (class C) |
| `attach <i>`, `cancel <i>` | Follow the running operation again; ask it to stop at its next safe point |
| `status [<i>]`, `doctor <i>`, `list`, `ps <i>`, `logs <i> <service> [--since T]`, `history <i>`, `bundles <i>` | Look without changing anything (`status` ends with exit 5 when something needs your attention) |
| `scheduled backup <i>`, `scheduled verify <i> <bundle>\|--latest [--restore-test]`, `scheduled task <i> <task> …`, `scheduled status` | Jobs for the machine's scheduler: classes A and B only, one line when they succeed (`scheduled status` prints only what changed) |
| `selftest [--host\|--offline]` | Run throwaway apps from start to end; `--host` also certifies this machine's system and Docker build; `--offline` checks the image without Docker |
