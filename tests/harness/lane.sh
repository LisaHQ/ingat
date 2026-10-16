#!/bin/sh
# One real-Docker lane (ARCHITECTURE.md §10.1): a scratch dind daemon reachable only through its unix socket, the
# pipeline's tested tool image loaded into it (ADR-0029), the unit suite run inside that exact image, the T1 suites
# driven from test-runner containers on the same daemon, then the M0 spike (spike/run.sh) as evidence that never
# changes the lane's verdict.
# Writes out/lane-<name>.json with the lane's verdict (PASS, FAIL or BLOCKED) for tests/harness/tested_json.py and
# out/spike-<name>/ with the spike's summary and logs.
# usage: sh tests/harness/lane.sh <dind image ref> <lane name> [unittest pattern for tests/docker] [image tarball]
# The image tarball is this lane's architecture of the image the pipeline built once (CI always passes it); without
# it, a local run builds the image inside the dind from image/versions.lock. INGAT_TEST_FULL_MATRIX=1 in the caller's
# environment (a nightly run) reaches the test runners and adds the generated crash matrix
# (tests/docker/test_it_crash_matrix.py).
# The tests/docker modules run in parallel processes, each with scratch hosts of its own (tests/harness/host.py):
# first SOLO alone, which in a lane (INGAT_TEST_LANE) counts every object and event of the daemon, so no other runner
# may be active; then one runner per group of `group` at once. The lane fails when any runner fails.
set -eu
repo=$(cd "$(dirname "$0")/../.." && pwd)
usage="usage: lane.sh <dind image> <lane> [pattern] [image tarball]"
dind=${1:?$usage}
lane=${2:?$usage}
pattern=${3:-test_*.py}
image_tar=${4:-}
SOLO=test_it_no_trace
# The runner of each module: groups of about equal wall time, measured on both engines (a module no line names, a new
# one included, runs in group 4); the generated crash matrix, nightly only, has a runner of its own.
group() {
  case $1 in
    test_it_session | test_it_gate | test_host_init) echo 1 ;;
    test_it_crash | test_it_lifecycle | test_backup_planning | test_status) echo 2 ;;
    test_it_upgrade | test_it_secrets | test_cli | test_floors | test_adapters | test_planning) echo 3 ;;
    test_it_crash_matrix) echo 5 ;;
    *) echo 4 ;;
  esac
}
mkdir -p "$repo/out"
logs=$(mktemp -d)
verdict=BLOCKED cid=
facts='{"lane":"'"$lane"'","result":"@RESULT@"}'
# Removes only the dind this run created (by ID), never a same-name container of another run.
cleanup() {
  [ -z "$cid" ] || docker rm -f -v "$cid" >/dev/null 2>&1 || true
  rm -rf "$logs"
  printf '%s\n' "$facts" | sed "s/@RESULT@/$verdict/" > "$repo/out/lane-$lane.json"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP
[ -z "$image_tar" ] || [ -r "$image_tar" ] || { echo "lane $lane: cannot read $image_tar" >&2; exit 2; }
# An explicit dockerd command skips the image entrypoint's default TCP listener (2375 or 2376): unix socket only.
cid=$(docker create --privileged --name "ingat-lane-$lane" --label ingat.scratch=1 -v "$repo:/work" "$dind" \
  dockerd --host=unix:///var/run/docker.sock)
docker start "$cid" >/dev/null
# No docker exec before dockerd logs "API listen": the docker:24.0.2-dind script enables cgroup v2 nesting without a
# retry, so a process exec'd into the container at that moment makes it exit ("sed: write error", exit 4).
up() { docker logs "$cid" 2>&1 | grep -q 'API listen on /var/run/docker.sock' && docker exec "$cid" docker info >/dev/null 2>&1; }
i=0
until up; do
  i=$((i + 1)); [ "$i" -lt 60 ] || { echo "dind did not start" >&2; docker logs --tail 30 "$cid" >&2; exit 1; }; sleep 1
done
dx() { docker exec -e INGAT_FORBIDDEN_NAMES -e INGAT_TEST_FULL_MATRIX -e INGAT_TEST_LANE -e GITHUB_ACTIONS "$cid" "$@"; }
if [ -n "$image_tar" ]; then
  loaded=$(docker exec -i "$cid" docker load -q < "$image_tar" \
    | sed -n 's/^Loaded image ID: //p; s/^Loaded image: //p' | tail -n 1)
  [ -n "$loaded" ] || { echo "lane $lane: $image_tar loaded no image" >&2; exit 1; }
  dx docker tag "$loaded" ingat:test
else
  dx sh /work/image/build.sh ingat:test
fi
# The test runner mounts the labelled probe volume where the wrapper mounts it (ARCHITECTURE §3.3), created first as
# install.sh creates it: a bare `-v ingat-probe:...` would create it without its label.
dx sh -c 'docker volume inspect ingat-probe >/dev/null 2>&1 \
  || docker volume create --label io.github.lisahq.ingat.role=probe ingat-probe >/dev/null'
run() { dx docker run --rm --network host -v /var/run/docker.sock:/var/run/docker.sock -v /srv:/srv -v /work:/work \
  -v ingat-probe:/run/ingat/docker-root:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 -e INGAT_FORBIDDEN_NAMES \
  -e INGAT_TEST_FULL_MATRIX -e INGAT_TEST_IMAGE=ingat:test -e INGAT_TEST_LANE --entrypoint python3 ingat:test "$@"; }
tool() { dx docker run --rm -v /var/run/docker.sock:/var/run/docker.sock --entrypoint docker ingat:test "$@"; }
engine=$(dx docker version --format '{{.Server.Version}}' | cut -d. -f1,2)
arch=$(dx docker version --format '{{.Server.Arch}}')
# The verdict names the daemon's architecture, so the image must be that architecture's variant (never emulated).
image_arch=$(dx docker image inspect --format '{{.Architecture}}' ingat:test)
[ "$image_arch" = "$arch" ] || { echo "lane $lane: the image is $image_arch, the daemon $arch" >&2; exit 1; }
cli=$(tool version --format '{{.Client.Version}}')
compose=$(tool compose version --short)
facts='{"lane":"'"$lane"'","engine":"'"$engine"'","arch":"'"$arch"'","cli":"'"$cli"'","compose":"'"$compose"'","result":"@RESULT@"}'
verdict=FAIL
run -m unittest discover -s tests/unit -t /work
selected=
for f in "$repo"/tests/docker/test_*.py; do
  m=$(basename "$f" .py)
  case "$m.py" in $pattern) selected="$selected $m" ;; esac
done
failed=0
case " $selected " in *" $SOLO "*)
  s=$(date +%s)
  export INGAT_TEST_LANE="$lane"
  run -m unittest -v "tests.docker.$SOLO" || failed=1
  unset INGAT_TEST_LANE
  echo "== tests/docker $SOLO alone: $(($(date +%s) - s))s" ;;
esac
started=
for g in 1 2 3 4 5; do
  mods=
  for m in $selected; do
    [ "$m" = "$SOLO" ] || [ "$(group "$m")" != "$g" ] || mods="$mods tests.docker.$m"
  done
  [ -n "$mods" ] || continue
  # shellcheck disable=SC2086 # one word per module
  (s=$(date +%s) rc=0; run -m unittest -v $mods > "$logs/$g.log" 2>&1 || rc=$?
   echo "$rc $(($(date +%s) - s))$mods" > "$logs/$g.rc") &
  started="$started $g"
done
wait
for g in $started; do
  { read -r rc took mods < "$logs/$g.rc"; } 2>/dev/null || rc="lost" took="?" mods="(runner gone)"
  echo "== tests/docker runner $g: exit $rc after ${took}s: $mods"
  cat "$logs/$g.log" 2>/dev/null || true
  [ "$rc" = 0 ] || failed=1
done
[ "$failed" = 0 ] || exit 1
verdict=PASS
# M0 spike (ROADMAP.md M0) against this daemon; S8 compares with the dind's own df of its Docker root. No command
# below can end the script with an error, so nothing changes the verdict any more.
root_df=$(dx df -Pk /var/lib/docker | awk 'NR == 2 { print $2, $4 }')
dx docker run --rm --init --network host -v /var/run/docker.sock:/var/run/docker.sock -v /srv/spike:/srv/spike \
  -v /work/spike:/spike:ro -e SPIKE_DOCKER_ROOT_DF="$root_df" -e GITHUB_ACTIONS --entrypoint sh ingat:test \
  /spike/run.sh /srv/spike ingat:test || echo "lane $lane: a spike item did not pass (out/spike-$lane/summary.txt)" >&2
rm -rf "$repo/out/spike-$lane"
docker cp "$cid:/srv/spike" "$repo/out/spike-$lane" || echo "lane $lane: the spike logs could not be copied" >&2
