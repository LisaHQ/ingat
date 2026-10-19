"""Docker CLI adapter (ARCHITECTURE §4.1, §9.3, §9.7): queries are free; every effect takes an EffectToken, which only
the executor issues inside an open, journaled step. Only the local daemon, never prune, never a forced removal."""

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from ingat.adapters import runner
from ingat.adapters.runner import Redactor, Result
from ingat.model.errors import CannotRun, Failed, IngatError

QUERY_TIMEOUT = 60.0
QUERY_LIMIT = 1 << 26  # capture limit for output that is parsed; a truncated one is refused, never parsed in part
PULL_TIMEOUT = 3600.0
NAME_WAIT = 15.0  # an exited --rm container's name can stay taken for a moment (Engine 29)
POLL = 0.25
PROJECT_LABEL = "com.docker.compose.project"
LOGGING = ("--log-driver", "local", "--log-opt", "max-size=10m", "--log-opt", "max-file=3")
# The CLI's own line, never a substring: task and probe stderr (app text) shares the stream.
_UNREACHABLE = re.compile(
    r"(?im)^(docker: )?(cannot|failed to|permission denied while trying to) connect to the docker "
)
_MISSING = re.compile(r"no such (container|image|object|volume)|network \S+ not found", re.IGNORECASE)


class EffectToken:
    """Proof of an open, journaled step; constructed only by the executor (static lint)."""

    __slots__ = ("op", "step")

    def __init__(self, op: int, step: int) -> None:
        self.op, self.step = op, step


def cli(
    args: Sequence[str], config_dir: str, redactor: Redactor | None, *, timeout: float = QUERY_TIMEOUT, **kw: Any
) -> Result:
    """Run the docker CLI with only DOCKER_CONFIG added to the runner's base environment. An unreachable daemon is
    CannotRun whatever the command; any other non-zero exit is the caller's to judge."""
    res = runner.run(["docker", *args], env={"DOCKER_CONFIG": config_dir}, timeout=timeout, redactor=redactor, **kw)
    if res.code != 0 and _UNREACHABLE.search(res.err):
        why = (
            "Docker on this computer cannot be reached. Make sure Docker is running and that this user is allowed to "
            "use it, then try again."
        )
        raise CannotRun(why, code="daemon-unreachable")
    return res


def check(res: Result, what: str, error: type[IngatError] = CannotRun) -> Result:
    if res.code != 0:
        tail = res.err.strip()[-400:]
        why = (
            f"{what} did not succeed: it timed out" if res.timed_out else f"{what} did not succeed. Docker said: {tail}"
        )
        raise error(why, code="docker")
    return res


def whole(res: Result, what: str) -> str:
    """stdout of a successful call that is about to be parsed (run with limit=QUERY_LIMIT)."""
    if check(res, what).truncated:
        raise CannotRun(f"{what} did not succeed: its output exceeded {QUERY_LIMIT} bytes", code="docker")
    return res.out


def pairs(flag: str, values: Mapping[str, str]) -> list[str]:
    return [part for key, value in values.items() for part in (flag, f"{key}={value}")]


def _only_missing(res: Result) -> bool:
    """True when the command succeeded or failed only because named objects do not exist."""
    lines = res.err.strip().splitlines()
    return res.code == 0 or (not res.timed_out and bool(lines) and all(_MISSING.search(line) for line in lines))


class Docker:
    def __init__(self, *, config_dir: str, redactor: Redactor | None = None) -> None:
        self.config_dir, self.redactor = config_dir, redactor

    def _run(self, *args: str, **kw: Any) -> Result:
        return cli(args, self.config_dir, self.redactor, **kw)

    def _json(self, *args: str) -> dict[str, Any]:
        doc: dict[str, Any] = json.loads(whole(self._run(*args, limit=QUERY_LIMIT), f"docker {args[0]}"))
        return doc

    def _ids(self, args: Sequence[str], labels: Mapping[str, str]) -> list[str]:
        filters = [part for k, v in labels.items() for part in ("--filter", f"label={k}={v}")]
        return whole(self._run(*args, *filters, limit=QUERY_LIMIT), f"docker {args[0]}").split()

    # queries
    def version(self) -> dict[str, Any]:
        return self._json("version", "--format", "{{json .}}")

    def info(self) -> dict[str, Any]:
        return self._json("info", "--format", "{{json .}}")

    def inspect(self, kind: str, ids: Sequence[str]) -> list[dict[str, Any]]:
        """Inspect documents of `kind` (container, image, volume, network); objects that do not exist are left out."""
        if not ids:
            return []
        res = self._run(kind, "inspect", "--", *ids, limit=QUERY_LIMIT)
        out = whole(replace(res, code=0) if _only_missing(res) else res, f"docker {kind} inspect")
        docs: list[dict[str, Any]] = json.loads(out or "[]")
        return docs

    def containers(self, labels: Mapping[str, str] | None = None, project: str | None = None) -> list[dict[str, Any]]:
        """Inspect documents of every container, running or not, carrying all `labels` (and in Compose `project`)."""
        wanted = {**(labels or {}), **({PROJECT_LABEL: project} if project else {})}
        return self.inspect("container", self._ids(("ps", "-a", "-q", "--no-trunc"), wanted))

    def volumes(self, labels: Mapping[str, str]) -> list[dict[str, Any]]:
        return self.inspect("volume", self._ids(("volume", "ls", "-q"), labels))

    def networks(self, labels: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        return self.inspect("network", self._ids(("network", "ls", "-q", "--no-trunc"), labels or {}))

    def image(self, ref: str) -> dict[str, Any] | None:
        found = self.inspect("image", [ref])
        return found[0] if found else None

    def logs(self, name: str, *, since: str | None = None, tail: int | None = None) -> Result:
        opts = [*(["--since", since] if since else []), *(["--tail", str(tail)] if tail is not None else [])]
        return check(self._run("logs", *opts, "--", name), f"reading the log of {name} (docker logs)")

    def events(self, since: str, until: str, filters: Sequence[str] = ()) -> list[dict[str, Any]]:
        """Daemon events in [since, until] (label filters match container events only)."""
        opts = [*(part for f in filters for part in ("--filter", f)), "--format", "{{json .}}"]
        res = self._run("events", "--since", since, "--until", until, *opts, limit=QUERY_LIMIT)
        return [json.loads(line) for line in whole(res, "docker events").splitlines() if line.strip()]

    def probe_exec(self, container: str, argv: Sequence[str], timeout: float) -> Result:
        """A read-only probe in a running service container; the exit code is the probe's."""
        return self._run("exec", container, *argv, timeout=timeout)

    # effects
    def pull(self, t: EffectToken, ref: str, *, tick: Callable[[], None] | None = None) -> None:
        what = f"downloading the image {ref} (docker pull)"
        check(self._run("pull", "-q", "--", ref, timeout=PULL_TIMEOUT, tick=tick), what, Failed)

    def stop(self, t: EffectToken, name: str, grace: int) -> None:
        """Stop a container; one that is already gone counts as stopped."""
        res = self._run("stop", "-t", str(grace), "--", name, timeout=grace + QUERY_TIMEOUT)
        if not _only_missing(res):
            check(res, f"stopping the container {name} (docker stop)", Failed)

    def remove_container(self, t: EffectToken, cid: str) -> None:
        """Remove a stopped container, never forced and never with its volumes; one already gone counts as removed."""
        res = self._run("rm", "--", cid)
        if not _only_missing(res):
            check(res, "removing the stopped container (docker rm)", Failed)

    def launch_executor(
        self,
        *,
        name: str,
        image: str,
        args: Sequence[str],
        mounts: Sequence[str],
        env: Mapping[str, str],
        labels: Mapping[str, str],
    ) -> str:
        """Start a detached executor (or CLI-side helper) container of the tool image: the only token-free create.
        `env` holds non-secret values only; the image is never pulled. The name is a mutex: a container of that name
        that is still present after NAME_WAIT refuses the launch. Returns the container ID."""
        argv = ["run", "-d", "--rm", "--init", "--pull", "never", "--network", "host", "--stop-timeout", "120"]
        argv += [*LOGGING, "--name", name]
        argv += [*pairs("--label", labels), *(p for m in mounts for p in ("-v", m)), *pairs("-e", env), image, *args]
        deadline = time.monotonic() + NAME_WAIT
        while True:
            if not self.inspect("container", [name]):
                res = self._run(*argv)
                if res.code == 0:
                    return res.out.strip()
                if "Conflict" not in res.err:
                    check(res, f"starting the background worker container {name} (docker run)")
            if time.monotonic() >= deadline:
                raise CannotRun(f"container {name} is still present", code="executor-running")
            time.sleep(POLL)
