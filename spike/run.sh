#!/bin/sh
# ROADMAP.md M0 spike against the current Docker daemon: S1, S3-S8, S10 (lite) and S11-S14 run here; S2, S9 and S15
# are host checks and print BLOCKED. Runs as root in a container of the tool image with the daemon socket and a work
# directory DIR mounted at the same path. tests/harness/lane.sh runs it in CI; on a host (spike/ copied to the host):
#   docker run --rm --init --network host -v /var/run/docker.sock:/var/run/docker.sock -v DIR:DIR -v "$PWD/spike:/spike:ro" \
#     [-v ingat-probe:/run/ingat/docker-root:ro] [-e SPIKE_DOCKER_ROOT_DF="<size KiB> <available KiB>"] \
#     --entrypoint sh IMAGE /spike/run.sh DIR IMAGE
# SPIKE_DOCKER_ROOT_DF is columns 2 and 4 of `df -Pk <DockerRootDir>` taken on the host (S8). Prints one line per item
# (PASS, FAIL or BLOCKED, then the reason) into DIR/summary.txt and each item's log into DIR/<item>.log. Creates only
# objects named <run>-* or labelled ingat.spike=<run> and removes them at the end. Exit 1 when an item FAILs.
set -u
usage="usage: run.sh <absolute dir mounted at the same path> <tool image>"
DIR=${1:?$usage}
IMG=${2:?$usage}
case "$DIR" in /*) ;; *) echo "$usage" >&2; exit 2 ;; esac
case "$DIR" in *[!A-Za-z0-9/._-]*) echo "run.sh: the directory may contain only [A-Za-z0-9/._-]" >&2; exit 2 ;; esac
RUN=spk$(python3 -c 'import secrets; print(secrets.token_hex(4))') # unique per run: cleanup removes by this name
W=$DIR/$RUN
LBL=ingat.spike=$RUN
FAILED=0
ID=$(docker image inspect -f '{{.Id}}' "$IMG") || exit 2
ENGINE=$(docker version -f '{{.Server.Version}}') || exit 2
mkdir -p "$W" || exit 2

cleanup() {
  ids=$(docker ps -aq --filter "label=$LBL")
  [ -z "$ids" ] || docker rm -f $ids >/dev/null
  for p in s1 s4 s5 s6 s11 s12 s14; do
    ids=$(docker network ls -q --filter "label=com.docker.compose.project=$RUN-$p")
    [ -z "$ids" ] || docker network rm $ids >/dev/null
  done
  for k in network volume; do
    ids=$(docker $k ls -q --filter "label=$LBL")
    [ -z "$ids" ] || docker $k rm $ids >/dev/null
  done
  ! docker image inspect "$RUN-app:1.0" >/dev/null 2>&1 || docker rmi "$RUN-app:1.0" >/dev/null
  rm -rf "$W"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

x() { printf '$ %s\n' "$*" >&2; "$@"; set -- $?; printf '[exit %s]\n' "$1" >&2; return "$1"; }
ok() { if [ "$2" -eq 0 ]; then echo "ok: $1"; else echo "NOT ok: $1"; [ -n "$NOTOK" ] || NOTOK=$1; fi; }
end() { if [ -z "$NOTOK" ]; then V=PASS R=$1; else V=FAIL R="not shown: $NOTOK"; fi; }
line() { printf '%-4s %-7s %s\n' "$1" "$2" "$3" | tee -a "$DIR/summary.txt"; }
item() { V=FAIL R="no verdict" NOTOK=; "$2" >"$DIR/$1.log" 2>&1; line "$1" "$V" "$R"; [ "$V" != FAIL ] || FAILED=1; }
waitfor() { n=$(($1 * 2)); shift; until "$@" >/dev/null 2>&1; do n=$((n - 1)); [ "$n" -gt 0 ] || return 1; sleep 0.5; done; }
running() { [ "$(docker inspect -f '{{.State.Status}}' "$1" 2>/dev/null)" = running ]; }
gone() { ! docker inspect "$1" >/dev/null 2>&1; }
logged() { docker logs "$1" 2>&1 | grep -q "$2"; }
port() { python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }
get() { python3 -c 'import sys, urllib.request as u; print(u.urlopen(sys.argv[1], timeout=5).status)' "$1"; }
C() { p=$1; shift; docker compose -p "$RUN-$p" --project-directory "$W/$p" -f "$W/$p/compose.yaml" "$@"; }
fstype() { awk -v p="$1" '(p == $2 || index(p, ($2 == "/" ? "" : $2) "/") == 1) && length($2) >= length(m) { m = $2; t = $3 } END { print t }' /proc/mounts; }

s1() {
  d=$W/s1; mkdir -p "$d/data"; echo "bind-$RUN" > "$d/data/f"; echo "secret-$RUN" > "$d/tok"
  printf "S1_VALUE='env-%s'\n" "$RUN" > "$d/app.env"
  cat > "$d/compose.yaml" <<EOF
services:
  s:
    image: "$ID"
    entrypoint: ["sh", "-c"]
    command: ['echo "\$\$(cat /data/f)|\$\$S1_VALUE|\$\$(cat /run/secrets/tok)"']
    labels: {ingat.spike: "$RUN"}
    volumes: ["$d/data:/data:ro"]
    env_file: ["$d/app.env"]
    secrets: [tok]
secrets:
  tok: {file: "$d/tok"}
EOF
  out=$(C s1 run --rm --no-deps -T s); echo "seen: $out"
  [ "$out" = "bind-$RUN|env-$RUN|secret-$RUN" ]; ok "a same-path bind, an env_file and a file secret resolve" $?
  end "same-path binds, env_file and file secrets resolve when Compose runs in the tool container"
}

s3() {
  d=$W/s3; mkdir -p "$d"; : > "$d/lock"
  nb='import fcntl, sys
f = open(sys.argv[1], "a+")
try:
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit("refused")
print("acquired")'
  x docker run -d --name "$RUN-s3-a" --label "$LBL" -v "$d:$d" --entrypoint python3 "$ID" -c 'import fcntl, sys, time
f = open(sys.argv[1], "a+")
fcntl.flock(f, fcntl.LOCK_EX)
print("locked", flush=True)
time.sleep(600)' "$d/lock"
  waitfor 30 logged "$RUN-s3-a" locked; ok "container A holds LOCK_EX" $?
  x docker run --rm --label "$LBL" -v "$d:$d" --entrypoint python3 "$ID" -c "$nb" "$d/lock"
  [ $? = 1 ]; ok "another container is refused while A holds the lock" $?
  x python3 -c "$nb" "$d/lock"; [ $? = 1 ]; ok "the tool container is refused while A holds the lock" $?
  x docker kill "$RUN-s3-a"
  x python3 -c "$nb" "$d/lock"; ok "the lock is free once A is SIGKILLed" $?
  end "flock on a same-path bind ($(fstype "$d")) excludes across containers and is freed by SIGKILL"
}

s4() {
  d=$W/s4; mkdir -p "$d/data"; echo "bind-$RUN" > "$d/data/f"; PORT=$(port)
  printf "PORT='%s'\n" "$PORT" > "$d/c.env"
  cat > "$d/compose.yaml" <<EOF
services:
  web:
    image: "$ID"
    entrypoint: ["sh", "-c"]
    command: ["exec python3 -m http.server 8080 --bind 0.0.0.0"]
    ports: ["127.0.0.1:\${PORT}:8080"]
    labels: {ingat.spike: "$RUN"}
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/', timeout=2)"]
      interval: 1s
      timeout: 3s
      retries: 30
EOF
  c4() { C s4 --env-file "$W/s4/c.env" "$@"; }
  x docker version -f 'client {{.Client.Version}} (API {{.Client.APIVersion}}), engine {{.Server.Version}} (API {{.Server.APIVersion}})'
  ok "the docker CLI negotiates an API version with the engine" $?
  x docker compose version; ok "the Compose plugin runs" $?
  x c4 config --format json --no-env-resolution > "$d/model.json"
  python3 -c 'import json, sys; sys.exit("web" not in json.load(open(sys.argv[1]))["services"])' "$d/model.json"
  ok "config --format json --no-env-resolution prints the model" $?
  h=$(c4 config --hash web); echo "config --hash web: $h"
  printf '%s\n' "$h" | grep -Eq '^web [0-9a-f]{64}$'; ok "config --hash prints <service> <sha256>" $?
  x c4 up -d --wait --no-build --pull never web; ok "up -d --wait --no-build --pull never" $?
  [ "web $(docker inspect -f '{{index .Config.Labels "com.docker.compose.config-hash"}}' "$RUN-s4-web-1")" = "$h" ]
  ok "the container's config-hash label equals config --hash" $?
  c4 run --rm --no-deps -T --name "$RUN-s4-x1" --label "$LBL" --label ingat.spike.step=1 \
    -v "$d/data:/mnt/data:ro" web 'cat /mnt/data/f; sleep 2; exit 3' > "$d/run.out" 2>&1 &
  pid=$!
  waitfor 30 running "$RUN-s4-x1"
  seen=$(docker inspect -f '{{index .Config.Labels "ingat.spike.step"}} {{json .HostConfig.Binds}}' "$RUN-s4-x1")
  wait "$pid"; rc=$?; cat "$d/run.out"; echo "while running: $seen; exit $rc"
  [ "$rc" = 3 ] && grep -q "bind-$RUN" "$d/run.out" && [ "${seen%% *}" = 1 ]
  ok "run --rm --no-deps -T --name --label -v sets the label and bind and returns the task's exit code" $?
  end "the bundled CLI and Compose verbs work against Engine $ENGINE"
}

s5() {
  d=$W/s5; mkdir -p "$d/env" "$d/other"; printf "APP_MODE='one'\n" > "$d/env/a.env"; cp "$d/env/a.env" "$d/env/b.env"
  x docker create --name "$RUN-s5-src" --label "$LBL" "$ID"
  x docker commit -c "LABEL ingat.spike=$RUN" "$RUN-s5-src" "$RUN-app:1.0"
  x docker rm "$RUN-s5-src"
  x docker volume create --label "$LBL" "${RUN}_data_g1"
  cat > "$d/compose.yaml" <<EOF
services:
  web:
    image: $RUN-app:1.0
    build: {context: .}
    entrypoint: ["sh", "-c"]
    command: ["echo out-line; echo err-line >&2; exec sleep 600"]
    ports: ["127.0.0.1:$(port):8080"]
    volumes: ["data:/data"]
    networks: [inner]
volumes:
  data: {}
networks:
  inner: {}
EOF
  ovr() { # ovr <file> <env file> <logging> [extra labels]
    cat > "$1" <<EOF
services:
  web:
    image: "$ID"
    pull_policy: "never"
    build: !reset null
    ports: !reset []
    env_file: ["$2"]
    labels: {"ingat.spike": "$RUN"${4:-}}
    logging: $3
volumes:
  data: {name: "${RUN}_data_g1", external: true}
networks:
  inner: {internal: true, labels: {"ingat.spike": "$RUN"}}
EOF
  }
  local3='{driver: "local", options: {"max-size": "10m", "max-file": "3"}}'
  ovr "$d/o.yaml" "$d/env/a.env" "$local3"
  x C s5 -f "$d/o.yaml" up -d --wait --no-build --pull never web; ok "up with the override" $?
  c=$RUN-s5-web-1
  [ "$(docker inspect -f '{{.Image}}' "$c")" = "$ID" ]; ok "the container runs the pinned image ID, not the decoy tag" $?
  [ "$(docker inspect -f '{{.HostConfig.LogConfig.Type}} {{index .HostConfig.LogConfig.Config "max-file"}}' "$c")" = "local 3" ]
  ok "logging driver local with rotation" $?
  [ "$(docker inspect -f '{{len .HostConfig.PortBindings}}' "$c")" = 0 ]; ok "ports !reset [] publishes nothing" $?
  [ "$(docker network inspect -f '{{.Internal}}' "$RUN-s5_inner")" = true ]; ok "the network is internal" $?
  docker inspect -f '{{range .Mounts}}{{.Name}} {{end}}' "$c" | grep -q "${RUN}_data_g1"; ok "the external volume is mounted" $?
  waitfor 10 logged "$c" err-line && logged "$c" out-line; ok "docker logs reads stdout and stderr" $?
  chash() { C s5 -f "$1" config --hash web; }
  h0=$(chash "$d/o.yaml"); echo "base hash: $h0"
  differs() { h=$(chash "$1"); echo "$h"; [ -n "$h" ] && [ -n "$h0" ] && [ "$h" != "$h0" ]; }
  same() { h=$(chash "$1"); echo "$h"; [ -n "$h" ] && [ "$h" = "$h0" ]; }
  ovr "$d/a.yaml" "$d/env/a.env" "$local3" ', "ingat.spike.extra": "1"'
  differs "$d/a.yaml"; ok "(a) a label change changes config --hash" $?
  ovr "$d/b.yaml" "$d/env/a.env" '{driver: "local", options: {"max-size": "10m", "max-file": "4"}}'
  differs "$d/b.yaml"; ok "(b) a logging change changes config --hash" $?
  ovr "$d/c.yaml" "$d/env/b.env" "$local3"
  same "$d/c.yaml"; ok "(c) an env_file path change with the same content keeps it" $?
  cp "$d/o.yaml" "$d/other/o.yaml"
  same "$d/other/o.yaml"; ok "(f) the same override at another path keeps it" $?
  printf "APP_MODE='two'\n" > "$d/env/a.env"
  differs "$d/o.yaml"; ok "(d) a change of the env_file content changes it" $?
  printf "APP_MODE='one'\n" > "$d/env/a.env"
  ovr "$d/t.yaml" "$d/env/a.env" '{driver: "none"}'
  before=$(docker inspect -f '{{.Id}}' "$c")
  out=$(C s5 -f "$d/t.yaml" run --rm --no-deps -T web 'echo terminal-line'); echo "$out"
  [ "$out" = terminal-line ]; ok "a run with logging driver none still prints to the terminal" $?
  [ "$(docker inspect -f '{{.Id}}' "$c")" = "$before" ]; ok "that run does not recreate the live container" $?
  x C s5 -f "$d/o.yaml" down
  end "the override pins the image ID, logs with local, resets ports, uses internal networks and external volumes"
}

s6() {
  d=$W/s6; mkdir -p "$d"
  python3 - "$d" "$ID" "$RUN" <<'PY'
import json, sys
d, image, run = sys.argv[1:]
vals = ["a$b", "${HOME}x", "with space", "hash # not comment", 'has "double" quotes', "back\\slash\\n", "$$dollar",
        "trail  ", "a#b", "%{x} `cmd` $(cmd) ${UNSET:-dflt}", "", "tab\there"]
json.dump(vals, open(f"{d}/expected.json", "w"))
with open(f"{d}/c.env", "w") as c, open(f"{d}/app.env", "w") as a:
    for i, v in enumerate(vals):
        c.write(f"V{i}='{v}'\n")
        a.write(f"E{i}='{v}'\n")
env = "".join(f'      V{i}: "${{V{i}}}"\n' for i in range(len(vals)))
open(f"{d}/compose.yaml", "w").write(f"""services:
  s:
    image: "{image}"
    entrypoint: ["python3", "-c"]
    command: ["import os, json; print(json.dumps(dict(os.environ)))"]
    labels: {{ingat.spike: "{run}"}}
    env_file: ["{d}/app.env"]
    environment:
{env}""")
PY
  x C s6 --env-file "$d/c.env" run --rm --no-deps -T s > "$d/seen.json"
  python3 - "$d" <<'PY'
import json, sys
d = sys.argv[1]
exp = json.load(open(f"{d}/expected.json"))
seen = json.loads(open(f"{d}/seen.json").read().strip().splitlines()[-1])
bad = [f"{p}{i}={seen.get(f'{p}{i}')!r}" for p in "VE" for i, v in enumerate(exp) if seen.get(f"{p}{i}") != v]
print("mismatched:", bad or "none")
sys.exit(1 if bad else 0)
PY
  ok "12 single-quoted values reach the container literally through --env-file and env_file" $?
  end "single-quoted values in --env-file and env_file are literal"
}

s7() {
  [ -n "${PORT:-}" ] || { V=BLOCKED R="needs the service S4 publishes"; return; }
  x get "http://127.0.0.1:$PORT/"; ok "HTTP 200 from 127.0.0.1:$PORT" $?
  end "a --network host tool container reaches 127.0.0.1:<published port>"
}

s8() {
  st='import os, sys; s = os.statvfs(sys.argv[1]); print(s.f_blocks * s.f_frsize // 1024, s.f_bavail * s.f_frsize // 1024)'
  if [ -d /run/ingat/docker-root ]; then
    src="the ingat-probe volume"; got=$(python3 -c "$st" /run/ingat/docker-root)
  else
    src="a fresh volume"; x docker volume create --label "$LBL" "$RUN-probe"
    got=$(docker run --rm --label "$LBL" -v "$RUN-probe:/p:ro" --entrypoint python3 "$ID" -c "$st" /p)
  fi
  echo "statvfs of $src (size, available KiB): $got; df -Pk of DockerRootDir: ${SPIKE_DOCKER_ROOT_DF:-not given}"
  [ -n "${SPIKE_DOCKER_ROOT_DF:-}" ] || { V=BLOCKED R="needs SPIKE_DOCKER_ROOT_DF from the host (statvfs of $src: $got KiB)"; return; }
  # shellcheck disable=SC2086
  set -- $got $SPIKE_DOCKER_ROOT_DF
  [ "$#" = 4 ] && [ $(($1 > $3 ? $1 - $3 : $3 - $1)) -le 1 ] && [ $(($2 > $4 ? $2 - $4 : $4 - $2)) -le $(($1 / 100)) ]
  ok "same size, available space within 1 %" $?
  end "statvfs on $src equals df of DockerRootDir"
}

s10() {
  out=$(docker run --rm -i --label "$LBL" --entrypoint sh "$ID" -c '[ -t 0 ] && echo tty || echo no-tty' </dev/null)
  echo "docker run -i without a terminal: $out"; [ "$out" = no-tty ]; ok "-i without a terminal gives no TTY" $?
  x docker run --rm -i -t --label "$LBL" --entrypoint true "$ID" </dev/null; [ $? -ne 0 ]
  ok "-i -t without a terminal is refused, so the wrapper passes -t only with one" $?
  x python3 -c 'import os, pty, select, sys, time
name, label, image = sys.argv[1:]
argv = ["docker", "run", "--rm", "-i", "-t", "--init", "--name", name, "--label", label, "--entrypoint", "sh", image,
        "-c", "[ -t 0 ] && echo IS-TTY; trap \"echo GOT-INT; exit 130\" INT; sleep 60 & wait"]
pid, fd = pty.fork()
if pid == 0:
    os.execvp(argv[0], argv)
buf, sent, code, end = b"", False, None, time.time() + 60
while code is None and time.time() < end:
    if select.select([fd], [], [], 0.5)[0]:
        try:
            buf += os.read(fd, 1024)
        except OSError:
            pass
    if not sent and b"IS-TTY" in buf:
        os.write(fd, b"\x03")
        sent = True
    done, status = os.waitpid(pid, os.WNOHANG)
    if done:
        code = os.waitstatus_to_exitcode(status)
print(buf.decode(errors="replace"), "exit", code)
sys.exit(0 if code == 130 and b"GOT-INT" in buf else 1)' "$RUN-s10" "$LBL" "$ID"
  ok "on a terminal the container sees a TTY and Ctrl-C ends it with 130" $?
  waitfor 20 gone "$RUN-s10"; ok "the --rm container is gone after Ctrl-C" $?
  end "-t only with a terminal; Ctrl-C reaches the container (the follower's prompt is the session-loss suite's)"
}

s11() {
  d=$W/s11; mkdir -p "$d"
  caps=$(docker info -f '{{.CPUCfsQuota}} {{.CPUCfsPeriod}} {{.MemoryLimit}} cgroup v{{.CgroupVersion}}')
  echo "CPU CFS quota, period, memory limit: $caps"
  cat > "$d/compose.yaml" <<EOF
services:
  c0:
    image: "$ID"
    entrypoint: ["sleep", "600"]
    labels: {ingat.spike: "$RUN"}
    cpus: "0"
  d0:
    image: "$ID"
    entrypoint: ["sleep", "600"]
    labels: {ingat.spike: "$RUN"}
    deploy: {resources: {limits: {cpus: "0"}}}
EOF
  C s11 config --format json --no-env-resolution > "$d/model.json"
  python3 -c 'import json, sys
s = json.load(open(sys.argv[1]))["services"]
print({k: (v.get("cpus"), v.get("deploy")) for k, v in s.items()})
sys.exit(any(v.get("cpus") or (v.get("deploy") or {}).get("resources", {}).get("limits", {}).get("cpus") for v in s.values()))' "$d/model.json"
  ok 'cpus "0" is dropped from the merged model' $?
  x C s11 up -d --no-build --pull never c0
  [ "$(docker inspect -f '{{.HostConfig.NanoCpus}}' "$RUN-s11-c0-1")" = 0 ]; ok 'cpus "0" starts without a CPU limit' $?
  mem=$(docker run --rm --label "$LBL" --memory 256m --entrypoint sh "$ID" -c \
    'cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes')
  echo "memory limit seen in the container: $mem"; [ "$mem" = 268435456 ]; ok "--memory 256m applies" $?
  x docker run --rm --label "$LBL" --cpus 0.5 --entrypoint true "$ID"; rc=$?
  case "$caps" in
    "true true"*) [ "$rc" = 0 ]; ok "a non-zero cpus limit applies (CPU CFS present)" $? ;;
    *) [ "$rc" != 0 ]; ok "a non-zero cpus limit is refused (no CPU CFS)" $? ;;
  esac
  end "cpus \"0\" means no limit, --memory applies, non-zero cpus follows CPU CFS ($caps)"
}

s12() {
  mkdir -p "$W/s12"
  cat > "$W/s12/compose.yaml" <<EOF
services:
  probe:
    image: "$ID"
    entrypoint: ["cat", "/proc/net/route"]
    labels: {ingat.spike: "$RUN"}
    networks: [inner]
networks:
  inner: {internal: true}
EOF
  routes=$(C s12 run --rm --no-deps -T probe); rc=$?; printf '%s\n[exit %s]\n' "$routes" "$rc"
  [ "$rc" = 0 ] || { R="the probe did not run on an internal network"; return; }
  pending="the fx-pg hold check waits for fx-pg (M2)"
  if printf '%s\n' "$routes" | awk 'NR > 1 && $2 == "00000000" { f = 1 } END { exit !f }'; then
    R="Engine $ENGINE routes internal networks by default (fallback: nothing changes, the hold is harmless); $pending"
  else
    V=PASS R="no default IPv4 route on an internal network on Engine $ENGINE; $pending"
  fi
}

s13() {
  [ -n "${GITHUB_ACTIONS:-}" ] || { V=BLOCKED R="CI item: tests/harness/lane.sh runs it on GitHub-hosted runners"; return; }
  x get "http://127.0.0.1:${PORT:-0}/"; ok "port publishing on 127.0.0.1" $?
  x docker run --rm --label "$LBL" --entrypoint python3 "$ID" -c \
    'import socket; socket.create_connection(("registry-1.docker.io", 443), 10).close()'
  ok "outbound TCP from a bridge container (iptables NAT)" $?
  x docker network create --internal --label "$LBL" "$RUN-int"; ok "docker network create --internal" $?
  x docker run --rm --label "$LBL" --network "$RUN-int" --entrypoint true "$ID"; ok "a container runs on it" $?
  end "dind Engine $ENGINE on $(docker version -f '{{.Server.Arch}}'): iptables NAT, published ports, internal networks"
}

s14() {
  d=$W/s14; mkdir -p "$d"
  cat > "$d/compose.yaml" <<EOF
services:
  t:
    image: "$ID"
    entrypoint: ["sh", "-c"]
    labels: {ingat.spike: "$RUN"}
EOF
  x python3 -c 'import os, signal, subprocess, sys, time
name, argv = sys.argv[1], sys.argv[2:]
def state():
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}} AutoRemove={{.HostConfig.AutoRemove}}", name],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "gone"
def until(done):
    for _ in range(80):
        if done(state()):
            break
        time.sleep(0.5)
    return state()
p = subprocess.Popen(argv, start_new_session=True)
print("before the kill:", until(lambda s: s.startswith("running")))
os.killpg(p.pid, signal.SIGKILL)
p.wait()
time.sleep(1)
after = state()
print("1 s after SIGKILL of the client:", after)
end = until(lambda s: s == "gone" or s == "exited AutoRemove=false")
print("after the task ended:", end)
sys.exit(0 if after.startswith("running") and end == "gone" else 2 if end == "exited AutoRemove=false" else 1)' \
    "$RUN-s14-x1" docker compose -p "$RUN-s14" --project-directory "$d" -f "$d/compose.yaml" \
    run --rm --no-deps -T --name "$RUN-s14-x1" --label "$LBL" t 'sleep 8; exit 3'
  case $? in
    0) V=PASS R="daemon-side removal (AutoRemove): the task outlives a SIGKILLed client, then is removed; its exit code is lost" ;;
    2) V=PASS R="client-side removal: the exited task container remains after the client is SIGKILLed" ;;
    *) R="no conclusive observation (see the log)" ;;
  esac
}

printf 'spike %s: engine %s on %s, docker CLI %s, Compose %s, %s\n' "$RUN" "$ENGINE" \
  "$(docker version -f '{{.Server.Arch}}')" "$(docker version -f '{{.Client.Version}}')" \
  "$(docker compose version --short)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee "$DIR/summary.txt"
item S1 s1
line S2 BLOCKED "host check: SSH drop, closed terminal, killed client, root run from the host scheduler (owner)"
item S3 s3
item S4 s4
item S5 s5
item S6 s6
item S7 s7
item S8 s8
line S9 BLOCKED "host facts: ACL markers and backups permission (facts.sh local), persistence across a platform update"
item S10 s10
item S11 s11
item S12 s12
item S13 s13
item S14 s14
line S15 BLOCKED "the consumers' runtime images on the host's kernel (owner)"
exit "$FAILED"
