"""Compose adapter (ARCHITECTURE §6.1, ADR-0006): the app's own files plus the generated override, the rendered env
file, an explicit service list and an empty environment. There is no passthrough: never `down -v`, `--rmi`,
`--remove-orphans`, a build or a pull."""

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ingat.adapters.docker import QUERY_LIMIT, EffectToken, cli, pairs, whole
from ingat.adapters.runner import Redactor, Result
from ingat.model.errors import Refused

CONFIG_TIMEOUT = 120.0
# Compose also takes its own settings from the --env-file (COMPOSE_REMOVE_ORPHANS=true makes `up` delete orphan
# containers, COMPOSE_PROFILES adds profiles, DOCKER_DEFAULT_PLATFORM changes the image), so none may appear there.
_CONTROL = re.compile(rb"^[ \t]*(?:export[ \t]+)?((?:COMPOSE|DOCKER)_\w*)", re.M)


@dataclass(frozen=True)
class Project:
    name: str
    directory: str
    files: tuple[str, ...]  # relative to `directory` or absolute
    override: str | None
    env_file: str
    profiles: tuple[str, ...] = ()


def _explicit(services: Sequence[str]) -> Sequence[str]:
    if not services:
        raise Refused("internal: Compose needs an explicit service list", code="internal")
    return services


class Compose:
    def __init__(self, docker_config_dir: str, redactor: Redactor | None = None) -> None:
        self.config_dir, self.redactor = docker_config_dir, redactor

    def _run(self, p: Project, *verb: str, **kw: Any) -> Result:
        try:
            with open(p.env_file, "rb") as f:
                control = _CONTROL.findall(f.read())
        except FileNotFoundError:
            control = []  # Compose refuses a missing env file itself
        if control:
            why = (
                f"The app's settings set {control[0].decode()}, which is a Docker Compose or Docker control setting "
                "and is not allowed in an app's settings. Remove that setting from the app's settings, then plan again."
            )
            raise Refused(why, code="policy")
        files = [*(os.path.join(p.directory, f) for f in p.files), *([p.override] if p.override else [])]
        head = ["compose", "-p", p.name, "--project-directory", p.directory, *(x for f in files for x in ("-f", f))]
        head += ["--env-file", p.env_file, *(x for prof in p.profiles for x in ("--profile", prof))]
        return cli([*head, *verb], self.config_dir, self.redactor, **kw)

    def _config(self, p: Project, *opts: str) -> str:
        """stdout of `config` (warnings go to stderr); a failure is Refused with the redacted stderr."""
        res = self._run(p, "config", *opts, timeout=CONFIG_TIMEOUT, limit=QUERY_LIMIT)
        if res.code != 0:
            why = f"Docker Compose could not read the app's configuration for {p.name}. Nothing was changed. "
            why += "It timed out." if res.timed_out else f"Compose said: {res.err.strip()[-800:]}"
            raise Refused(why, code="compose-config")
        return whole(res, "compose config")

    # queries
    def config(self, p: Project) -> dict[str, Any]:
        """The merged model for the policy check and the fingerprint only; env_file contents never enter it."""
        model: dict[str, Any] = json.loads(self._config(p, "--format", "json", "--no-env-resolution"))
        return model

    def config_hashes(self, p: Project, services: Sequence[str]) -> dict[str, str]:
        """Compose's per-service config hash; every env_file must exist (its content enters the hash)."""
        out = self._config(p, "--hash", ",".join(_explicit(services)))
        return {svc: digest for svc, digest in (line.split() for line in out.splitlines() if line.strip())}

    def variables(self, p: Project) -> dict[str, bool]:
        """Variables the Compose files use -> whether Compose gives them a non-empty default (`${VAR:-x}`)."""
        doc = json.loads(self._config(p, "--variables", "--format", "json") or "{}")
        return {name: bool(v.get("DefaultValue")) for name, v in doc.items()}

    def ps(self, p: Project) -> list[dict[str, Any]]:
        out = whole(self._run(p, "ps", "-a", "--format", "json", limit=QUERY_LIMIT), "compose ps")
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    # effects
    def up(
        self, t: EffectToken, p: Project, services: Sequence[str], *, timeout: float, recreate: bool = False
    ) -> Result:
        """`recreate`: new containers even when their configuration is unchanged (anonymous volumes are kept)."""
        again = ["--force-recreate"] if recreate else []
        return self._run(
            p, "up", "-d", "--no-build", "--pull", "never", "--no-deps", *again, *_explicit(services), timeout=timeout
        )

    def stop(self, t: EffectToken, p: Project, services: Sequence[str], *, timeout: float) -> Result:
        return self._run(p, "stop", *_explicit(services), timeout=timeout)

    def down(self, t: EffectToken, p: Project, *, timeout: float) -> Result:
        """Remove the project's containers and networks; never its volumes or images."""
        return self._run(p, "down", timeout=timeout)

    def run(
        self,
        t: EffectToken,
        p: Project,
        service: str,
        argv: Sequence[str],
        *,
        name: str,
        labels: Mapping[str, str],
        volumes: Sequence[str] = (),
        user: str | None = None,
        env: Mapping[str, str] | None = None,
        tty: bool = False,
        stdin: bytes | int | str | None = None,
        stdout: str | int = "capture",
        timeout: float,
        tick: Callable[[], None] | None = None,
    ) -> Result:
        """One task container (`run --rm --no-deps`); `-T` unless the task reads the terminal. `env` holds non-secret
        values only. The daemon removes the container (AutoRemove) even if this client dies."""
        opts = ["--rm", "--no-deps", *([] if tty else ["-T"]), "--name", name, *pairs("--label", labels)]
        opts += [*(x for v in volumes for x in ("-v", v)), *(["-u", user] if user else []), *pairs("-e", env or {})]
        return self._run(p, "run", *opts, service, *argv, timeout=timeout, stdin=stdin, stdout=stdout, tick=tick)
