"""`validate <repo-dir> [--instance <file>]` (MANIFEST_SPEC §6.2): offline checks of an app repository, including the
rules that need Compose. Compose renders the models client-side, so no daemon is needed and nothing is written."""

import os
from typing import Any

from ingat import __version__, brand
from ingat.adapters import override
from ingat.model.errors import CannotRun, Refused
from ingat.model.instance import parse_instance, validate_against
from ingat.model.manifest import Manifest, parse_manifest
from ingat.ops import context as cx
from ingat.ops.context import Ctx
from ingat.store import fs, state

SAMPLE_ROOT = "/sample"  # sample tool paths: Compose renders them without their existing
SAMPLE_IMAGE = "sha256:" + "0" * 64


def validate(ctx: Ctx, repo_dir: str, instance_file: str | None = None) -> None:
    """Refused (code `invalid-app`) with every error, one per line, each naming its key or model path. A directory
    or file the command names that does not exist is a usage error (exit 2)."""
    repo_dir = os.path.abspath(repo_dir)
    if bad := [p for p, ok in ((repo_dir, os.path.isdir), (instance_file, os.path.isfile)) if p and not ok(p)]:
        raise CannotRun(f"{bad[0]} does not exist", code="usage")
    inst = parse_instance(fs.read(os.path.abspath(instance_file))) if instance_file else None
    path = os.path.join(repo_dir, inst.manifest_path if inst else brand.MANIFEST_FILE)
    if not os.path.isfile(path):
        raise Refused(f"{path} does not exist: not an app repository", code="invalid-app")
    m = parse_manifest(fs.read(path), tool_version=__version__)
    errs = validate_against(inst, m) if inst else []
    errs += [f"compose.files: {f} does not exist" for f in m.files if not os.path.isfile(os.path.join(repo_dir, f))]
    errs += cx.compose_files(repo_dir, m)  # Compose reads include and extends files before any rule sees them
    if not errs:
        errs = _compose_errors(ctx, repo_dir, m, dict(inst.params) if inst else {}, inst.name if inst else "sample")
    if errs:
        raise Refused("the app does not validate:\n" + "\n".join(errs), code="invalid-app")


def _compose_errors(ctx: Ctx, repo: str, m: Manifest, given: dict[str, str], name: str) -> list[str]:
    """Variables, the app model's roles, binds and secrets, and the policy over the live and the isolated model."""
    for n, (k, p) in enumerate(m.params.items()):
        if k not in given and (p.kind in ("port", "subnet", "image") or (p.kind == "string" and p.default is None)):
            samples = {"port": str(20000 + n), "subnet": f"10.250.{n % 16}.0/24", "image": SAMPLE_IMAGE}
            given[k] = samples.get(p.kind, "sample")
    layout = state.Layout(SAMPLE_ROOT, SAMPLE_ROOT + "-backups")
    tv = {"instance": name, "environment": "sample", "host": "sample", "release": "sample", "commit": "0" * 40}
    app_env = os.path.join(layout.env_dir(name), "0" * 64 + ".env")
    env = cx.params(m, layout, name, given, tv, {}, app_env)
    with cx.project(name, repo, m.files, env) as proj:
        variables = ctx.compose.variables(proj)
    undeclared = [v for v, has_default in variables.items() if not has_default and v not in m.params]
    errs = [f"compose: variable {v} has no default and is not a declared param" for v in undeclared]
    errs += [f"params.{k}: not used by the Compose files" for k in m.params if k not in variables]
    app = cx.config(ctx, name, repo, m.files, env)
    errs += cx.model_errors(m, app, env)
    images = dict.fromkeys(app["services"], SAMPLE_IMAGE)
    nets = list(app.get("networks") or {})
    kw: dict[str, Any] = {"instance": name, "ns": brand.LABEL_NS, "images": images, "stores": {}, "networks": nets}
    for project, spec, isolated in (
        (name, override.live(app["services"], **kw), False),
        (f"{name}--t1", override.isolated(app["services"], op=1, holds=m.holds, **kw), True),
    ):
        model = cx.config(ctx, project, repo, m.files, env, override.render(spec))
        errs += [f"{project}: {e}" for e in cx.policy_errors(m, model, spec, env, repo, True, isolated)]
    return errs
