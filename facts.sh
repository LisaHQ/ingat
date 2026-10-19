#!/bin/sh
# Read-only host facts for a host certification (ARCHITECTURE.md §10.4 step 1), run by the owner as root on the host:
#   sh facts.sh [--root /srv/ingat] [--backups /srv/ingat-backups] > facts.json
# Prints one JSON object. "platform" holds platform fields only (release files, the Engine package build, docker
# version, docker info capabilities, kernel, architecture, C library): the committed certification uses only it.
# "local" holds this unit's own facts (free space, memory, modes, ACLs, filesystems) and is NEVER committed.
# Nothing is written, and no platform name is tested: release files and commands are probed.
set -eu
ROOT=/srv/ingat BACKUPS=/srv/ingat-backups
while [ $# -gt 0 ]; do
  case "$1" in
    --root) [ $# -ge 2 ] && [ -n "$2" ] || { echo "facts: --root needs a folder path, for example --root /srv/ingat" >&2; exit 2; }; ROOT=$2; shift 2 ;;
    --backups) [ $# -ge 2 ] && [ -n "$2" ] || { echo "facts: --backups needs a folder path, for example --backups /srv/ingat-backups" >&2; exit 2; }; BACKUPS=$2; shift 2 ;;
    *) echo "facts: unknown option $1. Use: sh facts.sh [--root DIR] [--backups DIR] > facts.json (DIR is the folder you gave install.sh, if you changed the default)" >&2; exit 2 ;;
  esac
done
DOCKER=$(command -v docker) || { echo "facts: Docker is not installed on this machine, or the docker command cannot be found from this root shell. If Docker is already installed, open a root shell with sudo -i and run this script from there; if not, install Docker Engine 24.0 or later, then run this script again" >&2; exit 2; }
# The local socket only (ARCHITECTURE.md §9.7): DOCKER_HOST or a CLI context never points the facts at another daemon.
dk() { "$DOCKER" -H unix:///var/run/docker.sock "$@"; }
dk info >/dev/null 2>&1 || { echo "facts: cannot talk to Docker on this machine. Check that Docker is running, and run this script as the root user (type sudo -i, press Enter, then run the same command again)" >&2; exit 2; }

# A JSON string of $1 without control characters, or null when $1 is empty.
str() {
  if [ -z "$1" ]; then printf null; return; fi
  printf '"%s"' "$(printf '%s' "$1" | tr -d '\000-\037' | sed 's/\\/\\\\/g; s/"/\\"/g')"
}
# A JSON array of the lines of standard input.
lines() { printf '['; tr -d '\000-\011\013-\037' | sed 's/\\/\\\\/g; s/"/\\"/g; s/^/"/; s/$/"/' | paste -sd, - | tr -d '\n'; printf ']'; }
# A JSON object of the release and build keys of a KEY=value release file; other keys (a device model) are dropped.
release() {
  printf '{'; sep=
  while IFS='=' read -r k v || [ -n "$k" ]; do
    case "$k" in
      '#'*) continue ;;
      NAME | ID | ID_LIKE | PRETTY_NAME | VARIANT_ID | *VERSION* | *version* | *BUILD* | *build*) ;;
      major | minor | micro | nano | smallfixnumber | os_name) ;;
      *) continue ;;
    esac
    v=${v#\"}; v=${v%\"}; v=${v#\'}; v=${v%\'}
    printf '%s%s:%s' "$sep" "$(str "$k")" "$(str "$v")"; sep=,
  done < "$1"
  printf '}'
}
# "<package> <version>" of the package that ships the Engine: dpkg, rpm, or an appliance package directory whose INFO
# file (package="…", version="…") sits above the binary's target/ directory; empty when none is found.
engine_package() {
  bin=$(command -v dockerd || command -v docker) || return 0
  link=$(readlink "$bin" || true); real=$(readlink -f "$bin" || printf '%s' "$bin")
  if command -v dpkg-query >/dev/null && p=$(dpkg-query -S "$real" 2>/dev/null); then
    dpkg-query -W -f '${Package} ${Version}' "${p%%[:,]*}"
  elif command -v rpm >/dev/null && rpm -qf "$real" >/dev/null 2>&1; then
    rpm -qf --qf '%{NAME} %{VERSION}-%{RELEASE}' "$real"
  else
    for p in "$link" "$real"; do
      case "$p" in */target/*) ;; *) continue ;; esac
      [ -r "${p%%/target/*}/INFO" ] || continue
      sed -n -e 's/^package="\(.*\)"$/\1/p' -e 's/^version="\(.*\)"$/\1/p' "${p%%/target/*}/INFO" | paste -sd' ' -
      return 0
    done
  fi
}
# Local facts of directory $1: ls -ld (an ACL shows as "+" after the mode), df, the mount that holds it, ACL tools.
dirfacts() {
  if [ ! -d "$1" ]; then printf '{"path":%s,"exists":false}' "$(str "$1")"; return; fi
  ls_line=$(ls -ld "$1")
  case "$ls_line" in ??????????+*) acl=true ;; *) acl=false ;; esac
  read -r size avail <<EOF
$(df -Pk "$1" | awk 'NR == 2 { print $2, $4 }')
EOF
  read -r mnt fst opts <<EOF
$(awk -v p="$(cd "$1" && pwd -P)" '(p == $2 || index(p, ($2 == "/" ? "" : $2) "/") == 1) && length($2) >= length(m) {
  m = $2; t = $3; o = $4 } END { print m, t, o }' /proc/mounts)
EOF
  printf '{"path":%s,"ls":%s,"acl_marker":%s,"size_kib":%s,"available_kib":%s,"mount":%s,"fs_type":%s,"mount_options":%s' \
    "$(str "$1")" "$(str "$ls_line")" "$acl" "${size:-null}" "${avail:-null}" "$(str "$mnt")" "$(str "$fst")" "$(str "$opts")"
  for t in synoacltool getfacl; do
    command -v "$t" >/dev/null || continue
    case "$t" in synoacltool) a=-get ;; *) a=-p ;; esac
    printf ',"%s":%s' "$t" "$("$t" "$a" "$1" 2>&1 | lines)"
  done
  printf '}'
}

info() { dk info --format "$1"; }
files=; sep=
for f in /etc/os-release /etc.defaults/VERSION; do
  [ -r "$f" ] && { files="$files$sep\"$f\":$(release "$f")"; sep=,; }
done
driver_type=$(info '{{range .DriverStatus}}{{if eq (index . 0) "driver-type"}}{{index . 1}}{{end}}{{end}}')
case "$driver_type" in io.containerd.snapshotter.*) store=containerd ;; *) store=classic ;; esac
libc=$(if command -v ldd >/dev/null; then ldd --version 2>&1 | head -n 1; fi)
docker_root=$(info '{{.DockerRootDir}}')

printf '{"facts":1,"at":"%s","platform":{' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '"release_files":{%s},"engine_package":%s,"docker_version":%s,' "$files" "$(str "$(engine_package || true)")" \
  "$(dk version --format '{{json .Server}}')"
printf '"docker_info":%s,"image_store":"%s",' "$(info '{"server_version":{{json .ServerVersion}},"operating_system":{{json .OperatingSystem}},"os_version":{{json .OSVersion}},"os_type":{{json .OSType}},"architecture":{{json .Architecture}},"kernel":{{json .KernelVersion}},"storage_driver":{{json .Driver}},"logging_driver":{{json .LoggingDriver}},"cgroup_driver":{{json .CgroupDriver}},"cgroup_version":{{json .CgroupVersion}},"cpu_cfs_quota":{{json .CPUCfsQuota}},"cpu_cfs_period":{{json .CPUCfsPeriod}},"cpu_shares":{{json .CPUShares}},"cpuset":{{json .CPUSet}},"memory_limit":{{json .MemoryLimit}},"swap_limit":{{json .SwapLimit}},"pids_limit":{{json .PidsLimit}},"oom_kill_disable":{{json .OomKillDisable}},"live_restore":{{json .LiveRestoreEnabled}},"security_options":{{json .SecurityOptions}},"default_runtime":{{json .DefaultRuntime}},"init_binary":{{json .InitBinary}}}')" "$store"
printf '"capability_warnings":%s,' "$(info '{{range .Warnings}}{{.}}{{"\n"}}{{end}}' | grep '^WARNING: No ' | lines)"
printf '"kernel":%s,"architecture":%s,"libc":%s},' "$(str "$(uname -r)")" "$(str "$(uname -m)")" "$(str "$libc")"
printf '"local":{"root":%s,"backups":%s,"docker_root":%s,' "$(dirfacts "$ROOT")" "$(dirfacts "$BACKUPS")" "$(dirfacts "$docker_root")"
printf '"docker_socket":%s,"engine_binary":%s,' "$(str "$(ls -lL /var/run/docker.sock 2>&1)")" \
  "$(str "$(readlink -f "$(command -v dockerd || command -v docker)" || true)")"
printf '"memory_kib":{%s},' "$(awk '/^(MemTotal|MemAvailable|SwapTotal|SwapFree):/ { sub(":", "", $1); printf "%s\"%s\":%s", s, $1, $2; s = "," }' /proc/meminfo)"
printf '"driver_status":%s,"info_warnings":%s}}\n' "$(info '{{json .DriverStatus}}')" "$(info '{{json .Warnings}}')"
