"""The Up step and probes (ADR-0015): stability windows, any-of JSON values, the image identity check, smoke.
http probes run from the tool over host loopback and are not applicable in isolated projects."""

import time
from typing import Any

from ingat import brand
from ingat.adapters import http_probe
from ingat.adapters.docker import EffectToken
from ingat.core.plan import Step
from ingat.core.steps import ONEOFF_LABEL, SERVICE_LABEL, UP_TIMEOUT, Op, compose_up, safe_binds
from ingat.model import records
from ingat.model.errors import Failed, Refused

SLICE = 0.5
ATTEMPT_TIMEOUT = 30.0  # one probe attempt; the probe's own timeout bounds the whole wait
CONFIG_HASH = "com.docker.compose.config-hash"
_MISSING = object()


def dig(doc: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return _MISSING
        doc = doc[part]
    return doc


def matches(doc: Any, spec: dict[str, list[Any]]) -> bool:
    """Every dotted path holds one of its allowed values, compared with their JSON types (true is not 1)."""
    return all(
        any(type(v) is type(x) and v == x for x in allowed)
        for v, allowed in ((dig(doc, p), a) for p, a in spec.items())
    )


def containers(op: Op, project: str) -> list[dict[str, Any]]:
    """The project's service containers that carry this instance's label (one-off task containers left out): a
    foreign container in the project's name is never probed, exec'd into or counted (F8)."""
    found = op.docker.containers(labels={brand.label("instance"): op.name}, project=project)
    return [c for c in found if (c["Config"].get("Labels") or {}).get(ONEOFF_LABEL) != "True"]


def attempt(op: Op, project: str, p: dict[str, Any]) -> tuple[bool, Any]:
    """One try of a probe: (passed, parsed JSON or None)."""
    e = p.get("expect") or {}
    limit = min(ATTEMPT_TIMEOUT, float(p.get("timeout", 60)))
    if p["kind"] == "http":
        try:
            status, headers, body = http_probe.request(
                p["port"], p["path"], method=p.get("method") or "GET", headers=p.get("headers"), body=p.get("body"),
                timeout=limit,
            )  # fmt: skip
        except Failed:
            return False, None
        text = body.decode(errors="replace")
        ok = status == e["status"] if e.get("status") is not None else 200 <= status < 300
        ok = ok and (e.get("body_contains") or "") in text
        ok = ok and all(headers.get(k.lower()) == v for k, v in (e.get("header_equals") or {}).items())
        ok = ok and all(v in headers.get(k.lower(), "") for k, v in (e.get("header_contains") or {}).items())
    else:
        running = [c for c in containers(op, project) if c["Config"]["Labels"].get(SERVICE_LABEL) == p["service"]]
        running = [c for c in running if c["State"]["Running"]]
        if not running:
            return False, None
        if p["kind"] == "health":
            return (running[0]["State"].get("Health") or {}).get("Status") == "healthy", None
        res = op.docker.probe_exec(running[0]["Name"].lstrip("/"), p["argv"], limit)
        ok, text = res.code == (e["exit"] if e.get("exit") is not None else 0), res.out
    if not e.get("json"):
        return ok, None
    try:
        doc = records.loads(text.encode())
    except Refused:
        return False, None
    return ok and matches(doc, e["json"]), doc


def wait(op: Op, project: str, p: dict[str, Any]) -> Any:
    """Until the probe passes continuously for `stable` seconds; Failed after `timeout`. Cancel ends the wait."""
    deadline = time.monotonic() + float(p.get("timeout", 60))
    since: float | None = None
    while True:
        ok, doc = attempt(op, project, p)
        now = time.monotonic()
        since = (now if since is None else since) if ok else None
        if since is not None and now - since >= float(p.get("stable", 0)):
            return doc
        if now >= deadline:
            why = (
                f"The app did not become ready in time: the readiness check '{p['name']}' did not stay passing for "
                f"{p.get('stable', 0)} seconds within the {p['timeout']}-second limit."
            )
            raise Failed(why, code="probe")
        end = min(deadline, now + float(p.get("interval", 2)))
        while (left := end - time.monotonic()) > 0:
            op.tick()
            time.sleep(min(SLICE, left))


def up(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    """`compose up` of the services, then each wait probe, the identity check and smoke."""
    a = step.args
    v = op.variant(a["variant"])
    proj = op.project(a["variant"])
    isolated = bool(v.get("isolated"))
    safe_binds(op, a["variant"])
    ev: dict[str, Any] = {"started": a["services"], "probes": {}}
    if a["services"]:
        compose_up(op, t, proj, a["services"], a.get("timeout", UP_TIMEOUT))
    for name in a.get("wait", []):
        p = v["probes"][name]
        if isolated and p["kind"] == "http":
            ev["probes"][name] = "n/a"
            continue
        doc = wait(op, proj.name, p)
        ev["probes"][name] = "pass"
        if name == a.get("schema_probe") and a.get("schema_paths"):
            exp, act = (dig(doc, x) for x in a["schema_paths"])
            if _MISSING in (exp, act):
                raise Failed(f"probe {name} reported no schema at {', '.join(a['schema_paths'])}", code="schema")
            ev["schema"] = {"expected": exp, "actual": act, "at": records.iso(records.utc_now())}
    found = containers(op, proj.name)
    if a.get("identity"):
        if not found:
            why = f"No running containers were found for {proj.name}, so it cannot be confirmed as running."
            raise Failed(why, code="identity")
        for c in found:
            svc = c["Config"]["Labels"].get(SERVICE_LABEL)
            if v["images"].get(svc) != c["Image"] or not c["State"]["Running"]:
                why = (
                    f"The service {svc} is not running, or it runs a different app build than the planned one "
                    f"({v['images'].get(svc)}), so the deployment cannot be confirmed."
                )
                raise Failed(why, code="identity")
    for p in v.get("smoke", []) if a.get("smoke") else []:
        if isolated and p["kind"] == "http":
            ev["probes"]["smoke:" + p["name"]] = "n/a"
        elif not attempt(op, proj.name, p)[0]:
            why = f"The final check '{p['name']}' failed: the app started but did not answer as expected."
            raise Failed(why, code="smoke")
        else:
            ev["probes"]["smoke:" + p["name"]] = "pass"
    if a.get("reopens_writes"):
        ev["writes_reopened_at"] = records.iso(records.utc_now())
    labels = {c["Config"]["Labels"].get(SERVICE_LABEL): c["Config"]["Labels"].get(CONFIG_HASH) for c in found}
    ev["config_hashes"] = {s: h for s, h in labels.items() if s in a["services"]}
    return ev
