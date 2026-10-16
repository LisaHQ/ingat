"""fx-lite: CI fixture mirroring the SQLite consumer pattern (one container: web app, job runner, SQLite WAL store).

Also serves fx-web (`web`). Standard library only; every command but `serve`, `web`, `probe` and `bootstrap`
prints one JSON object. Exit codes: 0 ok, 1 failed or refused decision, 2 refused input, usage error or preview.
"""

import hashlib
import json
import os
import secrets
import shutil
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_SCHEMA = (
    "CREATE TABLE jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,"
    " attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)",
    "CREATE TABLE outbound (id INTEGER PRIMARY KEY CHECK (id = 1), paused TEXT)",
    "INSERT INTO outbound VALUES (1, NULL)",
    "CREATE TABLE backups (name TEXT NOT NULL, at TEXT NOT NULL, outcome TEXT NOT NULL)",
    "CREATE TABLE codes (sha256 TEXT NOT NULL, config_sha256 TEXT, at TEXT NOT NULL)",
)


class Out(Exception):
    """Ends a command with an exit code and the JSON object to print."""

    def __init__(self, code: int, **doc: object) -> None:
        super().__init__(doc.get("message", ""))
        self.code, self.doc = code, doc


def usage(message: str) -> Out:
    return Out(2, outcome="usage-error", message=message)


def opts(args: list[str], valued: tuple[str, ...] = (), flags: tuple[str, ...] = ()) -> dict[str, str]:
    out: dict[str, str] = {}
    it = iter(args)
    for a in it:
        if a in out or (a not in valued and a not in flags):
            raise usage(f"unexpected argument {a!r}")
        value = next(it, None) if a in valued else "1"
        if value is None:
            raise usage(f"{a} needs a value")
        out[a] = value
    return out


def data_dir() -> str:
    return os.environ.get("DATA_DIR", "/data")


def target() -> int:
    return int(os.environ.get("FXLITE_SCHEMA", "1"))


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def connect(create: bool = True) -> sqlite3.Connection:
    path = os.path.join(data_dir(), "app.db")
    if not create and not os.path.isfile(path):
        raise Out(2, outcome="refused", message="the database does not exist")
    con = sqlite3.connect(path, timeout=30, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def schema(con: sqlite3.Connection) -> int:
    return int(con.execute("PRAGMA user_version").fetchone()[0])


def migrate_db() -> tuple[int, int]:
    """Migrates to FXLITE_SCHEMA in one exclusive transaction; a re-run applies nothing."""
    con = connect()
    want = target()
    con.execute("BEGIN EXCLUSIVE")
    try:
        have = schema(con)
        if have > want:
            raise Out(2, outcome="refused", message=f"database schema {have} is newer than this release ({want})")
        for v in range(have + 1, want + 1):
            for stmt in BASE_SCHEMA if v == 1 else (f"CREATE TABLE extra_{v} (id INTEGER PRIMARY KEY, value TEXT)",):
                con.execute(stmt)
        con.execute(f"PRAGMA user_version = {want}")
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    os.makedirs(os.path.join(data_dir(), "files"), exist_ok=True)
    return have, want


def cmd_migrate(args: list[str]) -> dict[str, object]:
    opts(args)
    have, want = migrate_db()
    return {"outcome": "ok", "from": have, "to": want}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(e: OSError) -> None:
    raise e


def tree(root: str) -> dict[str, str]:
    """sha256 of every file under root by relative path; an unreadable directory, a link or a special file fails."""
    files = {}
    for d, dirs, names in os.walk(root, onerror=fail):
        for n in dirs + names:
            p = os.path.join(d, n)
            if os.path.islink(p) or not (os.path.isdir(p) or os.path.isfile(p)):
                raise OSError(f"{os.path.relpath(p, root)}: not a regular file or directory")
            if n in names:
                files[os.path.relpath(p, root).replace(os.sep, "/")] = sha256(p)
    return files


def copy_files(src: str, dst: str, rels: Iterable[str]) -> None:
    """Copies the listed files with fresh modes, never those of a read-only bundle copy."""
    for rel in rels:
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(src, rel), target)


def cmd_backup(args: list[str]) -> dict[str, object]:
    o = opts(args, valued=("--to",))
    if "--to" not in o:
        raise usage("backup needs --to DIR")
    data, dest = os.path.realpath(data_dir()), os.path.realpath(o["--to"])
    if not os.path.isdir(dest) or dest == data or dest.startswith(data + os.sep):
        raise Out(2, outcome="refused", message="--to must be an existing directory outside the data directory")
    con = connect(create=False)
    have = schema(con)
    if not 0 < have <= target():
        raise Out(2, outcome="refused", message=f"database schema {have} does not match this release")
    name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = os.path.join(dest, name)
    try:
        os.mkdir(out, 0o700)
        copy = sqlite3.connect(os.path.join(out, "db.sqlite"))
        con.backup(copy)
        copy.execute("PRAGMA journal_mode=DELETE")
        copy.close()
        files = os.path.join(data, "files")
        os.mkdir(os.path.join(out, "files"))
        if os.path.isdir(files):
            copy_files(files, os.path.join(out, "files"), tree(files))
        manifest = {"format": 1, "schema": have, "release": os.environ.get("RELEASE", ""), "files": tree(out)}
        with open(os.path.join(out, "manifest.json"), "x") as f:
            json.dump(manifest, f, sort_keys=True)
    except (OSError, sqlite3.Error) as e:
        con.execute("INSERT INTO backups VALUES (?, ?, 'failed')", (name, now()))
        raise Out(1, outcome="failed", message=str(e)) from e
    con.execute("INSERT INTO backups VALUES (?, ?, 'ok')", (name, now()))
    return {"outcome": "ok", "name": name, "schema": have}


def cmd_restore(args: list[str]) -> dict[str, object]:
    o = opts(args, valued=("--from", "--to"))
    if len(o) != 2:
        raise usage("restore needs --from DIR --to DIR")
    src, dst = o["--from"], o["--to"]
    if not os.path.isdir(dst) or os.listdir(dst):
        raise Out(2, outcome="refused", message="--to must be an existing empty directory")
    try:
        with open(os.path.join(src, "manifest.json"), "rb") as f:
            listed = json.load(f)["files"]
        found = {k: v for k, v in tree(src).items() if k != "manifest.json"}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Out(1, outcome="failed", message=f"unreadable backup: {e}") from e
    if found != listed:
        raise Out(1, outcome="failed", message="backup files do not match their manifest")
    uri = "file:" + urllib.parse.quote(os.path.abspath(os.path.join(src, "db.sqlite"))) + "?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True)
        ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        have = schema(con)
        con.close()
    except sqlite3.Error as e:
        raise Out(1, outcome="failed", message=f"unreadable database: {e}") from e
    if not ok:
        raise Out(1, outcome="failed", message="database integrity check failed")
    if have > target():
        raise Out(2, outcome="refused", message=f"backup schema {have} is newer than this release ({target()})")
    copy_files(src, dst, listed)
    os.rename(os.path.join(dst, "db.sqlite"), os.path.join(dst, "app.db"))
    con = sqlite3.connect(os.path.join(dst, "app.db"), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE outbound SET paused = 'restored'")
    held = con.execute("UPDATE jobs SET state = 'held' WHERE state = 'queued'").rowcount
    con.execute("COMMIT")
    con.close()
    return {"outcome": "ok", "schema": have, "held": held}


def cmd_bootstrap(args: list[str]) -> int:
    o = opts(args, valued=("--config",), flags=("--new-code",))
    if len(o) != 1:
        raise usage("bootstrap needs --config FILE or --new-code")
    config = None
    if "--config" in o:
        try:
            with open(o["--config"], "rb") as f:
                body = f.read()
        except OSError as e:
            raise Out(1, outcome="refused", message=f"cannot read the config file: {e.strerror}") from e
        if not body:
            raise Out(1, outcome="refused", message="the config file is empty")
        config = hashlib.sha256(body).hexdigest()
    migrate_db()
    code = secrets.token_urlsafe(12)
    con = connect()
    con.execute("INSERT INTO codes VALUES (?, ?, ?)", (hashlib.sha256(code.encode()).hexdigest(), config, now()))
    con.close()
    print(code)
    return 0


def cmd_enqueue(args: list[str]) -> dict[str, object]:
    """Test helper: queues one outbound job."""
    o = opts(args, valued=("--kind",))
    migrate_db()
    job = secrets.token_hex(6)
    con = connect()
    con.execute("INSERT INTO jobs VALUES (?, ?, 'queued', 0, ?)", (job, o.get("--kind", "mail"), now()))
    con.close()
    return {"outcome": "ok", "job": job}


def cmd_queue(args: list[str]) -> dict[str, object]:
    action = args[0] if args else ""
    if action not in ("release", "resume", "drop"):
        raise usage("queue needs release, resume or drop")
    targeted = action != "resume"
    o = opts(args[1:], ("--job",) if targeted else (), ("--confirm", "--all") if targeted else ("--confirm",))
    if "--job" in o and "--all" in o:
        raise usage("--job and --all exclude each other")
    if targeted and "--confirm" in o and "--job" not in o and "--all" not in o:
        raise usage(f"queue {action} --confirm needs --job J or --all")
    migrate_db()
    con = connect()
    paused = con.execute("SELECT paused FROM outbound").fetchone()[0]
    rows = con.execute("SELECT id, kind, attempts FROM jobs WHERE state = 'held' ORDER BY created_at, id").fetchall()
    held = [{"id": i, "kind": k, "attempts": a} for i, k, a in rows if o.get("--job", i) == i]
    if "--confirm" not in o:
        doc: dict[str, object] = {"outcome": "preview", "action": action, "paused": paused}
        if action == "resume":
            queued = con.execute("SELECT count(*) FROM jobs WHERE state = 'queued'").fetchone()[0]
            doc.update(held=len(held), queued=queued)
        else:
            doc["held"] = held
        raise Out(2, **doc)
    if action == "resume":
        if held:
            raise Out(1, outcome="refused", message=f"{len(held)} held job(s) await a release or drop decision")
        con.execute("UPDATE outbound SET paused = NULL")
        return {"outcome": "ok", "action": action, "was_paused": paused}
    if not held:
        raise Out(1, outcome="refused", message="no matching held job")
    state = "queued" if action == "release" else "dropped"
    con.executemany("UPDATE jobs SET state = ? WHERE id = ?", [(state, j["id"]) for j in held])
    return {"outcome": "ok", "action": action, "jobs": [j["id"] for j in held]}


def deliver() -> None:
    """Delivers queued jobs unless outbound is paused; real sending needs DELIVERY_MODE=smtp and DELIVERY_ENABLED."""
    con = connect()
    try:
        if con.execute("SELECT paused FROM outbound").fetchone()[0] is not None:
            return
        smtp = os.environ.get("DELIVERY_MODE") == "smtp" and os.environ.get("DELIVERY_ENABLED") == "true"
        state = "sent" if smtp else "captured"
        os.makedirs(os.path.join(data_dir(), state), exist_ok=True)
        for job, kind in con.execute("SELECT id, kind FROM jobs WHERE state = 'queued'").fetchall():
            with open(os.path.join(data_dir(), state, job), "w") as f:
                json.dump({"id": job, "kind": kind}, f)
            con.execute("UPDATE jobs SET state = ?, attempts = attempts + 1 WHERE id = ?", (state, job))
    finally:
        con.close()


def run_jobs() -> None:
    while True:
        time.sleep(0.2)
        try:
            deliver()
        except (OSError, sqlite3.Error) as e:  # a busy database or a full disk: retried on the next round
            print(f"delivery failed: {e}", file=sys.stderr, flush=True)


class Route(BaseHTTPRequestHandler):
    def answer(self) -> tuple[int, object]:
        return 404, {"error": "not found"}

    def do_GET(self) -> None:
        status, doc = self.answer()
        body = (doc if isinstance(doc, str) else json.dumps(doc)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html" if isinstance(doc, str) else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class AppRoute(Route):
    def answer(self) -> tuple[int, object]:
        if self.path == "/api/health":
            return 200, {"status": "ok", "release": os.environ.get("RELEASE", "")}
        if self.path != "/api/ready":
            return super().answer()
        con = connect()
        actual = schema(con)
        con.close()
        writable = os.access(data_dir(), os.W_OK)
        ok = writable and actual == target()
        doc = {"status": "ready" if ok else "not-ready", "data_writable": writable}
        return (200 if ok else 503), doc | {"schema": {"expected": target(), "actual": actual}}


class WebRoute(Route):
    def answer(self) -> tuple[int, object]:
        release = os.environ.get("RELEASE", "")
        if self.path == "/health":
            return 200, {"status": "ok", "release": release}
        if self.path == "/":
            return 200, f"<!doctype html><title>fx-web</title><p>fx-web {escape(release)}</p>\n"
        return super().answer()


def listen(port: int, route: type[Route]) -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    ThreadingHTTPServer(("0.0.0.0", port), route).serve_forever()
    return 0


def cmd_serve(args: list[str]) -> int:
    opts(args)
    migrate_db()
    if os.environ.get("JOBS") != "off":
        threading.Thread(target=run_jobs, daemon=True).start()
    return listen(int(os.environ.get("PORT", "3000")), AppRoute)


def cmd_web(args: list[str]) -> int:
    opts(args)
    return listen(int(os.environ.get("PORT", "8080")), WebRoute)


def cmd_probe(args: list[str]) -> int:
    if len(args) != 1:
        raise usage("probe needs one URL")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(args[0], timeout=4) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    except (OSError, ValueError) as e:
        print(f"probe failed: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(body.decode(errors="replace"))
    return 0 if 200 <= status < 300 else 1


COMMANDS = {
    "serve": cmd_serve,
    "web": cmd_web,
    "migrate": cmd_migrate,
    "backup": cmd_backup,
    "restore": cmd_restore,
    "bootstrap": cmd_bootstrap,
    "queue": cmd_queue,
    "enqueue": cmd_enqueue,
    "probe": cmd_probe,
}


def main(argv: list[str]) -> int:
    try:
        if not argv or argv[0] not in COMMANDS:
            raise usage("commands: " + ", ".join(COMMANDS))
        result = COMMANDS[argv[0]](argv[1:])
    except Out as o:
        print(json.dumps(o.doc, sort_keys=True))
        return o.code
    if isinstance(result, int):
        return result
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
