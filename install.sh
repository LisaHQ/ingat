#!/bin/sh
# Install or upgrade Ingat on this machine (ARCHITECTURE.md §3.4, §3.5). Run it as root (sudo -i); the release's SHA256SUMS
# checksum file must be in the same folder as this script:
#   sh install.sh --version 0.1.0 [--root /srv/ingat] [--backups /srv/ingat-backups] [--from-tar FILE] [--link PATH]
# A platform profile passes its own roots (the DSM profile: --root /volume1/ingat --backups /volume1/ingat-backups).
set -eu
die() { echo "install: $1" >&2; exit "${2:-1}"; }
[ "$(id -u)" -eq 0 ] || die "run as root: this installer must be run by the root user (the top-level account of this machine), not by your normal user or a NAS admin user. Type sudo -i, press Enter, then run the same command again" 2
VERSION= ROOT=/srv/ingat BACKUPS=/srv/ingat-backups TAR= LINK=
while [ $# -gt 0 ]; do
  case "$1" in
    --version) [ $# -ge 2 ] && [ -n "$2" ] || die "--version needs a value, for example --version 0.1.0" 2; VERSION=$2; shift 2 ;;
    --root) [ $# -ge 2 ] && [ -n "$2" ] || die "--root needs a folder path, for example --root /srv/ingat" 2; ROOT=$2; shift 2 ;;
    --backups) [ $# -ge 2 ] && [ -n "$2" ] || die "--backups needs a folder path, for example --backups /srv/ingat-backups" 2; BACKUPS=$2; shift 2 ;;
    --from-tar) [ $# -ge 2 ] && [ -n "$2" ] || die "--from-tar needs the downloaded release file, for example --from-tar ingat-0.1.0-amd64.tar" 2; TAR=$2; shift 2 ;;
    --link) [ $# -ge 2 ] && [ -n "$2" ] || die "--link needs a path, for example --link /usr/local/bin/ingat" 2; LINK=$2; shift 2 ;;
    *) die "unknown option $1. The options are --version (required), --root, --backups, --from-tar and --link, for example: sh install.sh --version 0.1.0" 2 ;;
  esac
done
[ -n "$VERSION" ] || die "--version is missing. Tell the installer which version to install, for example: sh install.sh --version 0.1.0 (the version is on the release page)" 2
# The version is interpolated into the wrapper's heredoc: a semantic version only (X.Y.Z plus one optional -pre or
# +build suffix of [0-9A-Za-z.-]).
case "$VERSION" in *[!0-9A-Za-z.+-]*) die "--version must be a version number written as three numbers separated by dots, such as 0.1.0. The value you gave contains characters that are not allowed, so it was not used" 2 ;; esac
printf '%s\n' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$' \
  || die "--version must be a version number of three numbers separated by dots, such as 0.1.0 (a pre-release such as 1.2.0-rc.1 is also fine), not $VERSION. Use the release's number without the leading v: for release v0.1.0 type --version 0.1.0" 2
case "$ROOT$BACKUPS" in *[!A-Za-z0-9/._-]*) die "the folder paths given to --root and --backups may use only letters, digits and the characters / . _ and - (no spaces or other symbols), for example /srv/ingat" 2 ;; esac
case "$ROOT" in /*) ;; *) die "--root must be a full folder path that starts with /, for example --root /srv/ingat" 2 ;; esac
case "$BACKUPS" in /*) ;; *) die "--backups must be a full folder path that starts with /, for example --backups /srv/ingat-backups" 2 ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
SUMS=$HERE/SHA256SUMS
[ -r "$SUMS" ] || die "SHA256SUMS not found next to install.sh. SHA256SUMS is the small checksum file from the same release; it lets the installer confirm the download is complete and unchanged. Download it from the release page, put it in the same folder as install.sh, then run the installer again"
DOCKER=$(command -v docker) || die "Docker is not installed on this machine, or the docker command cannot be found from this root shell. If Docker is already installed, open a root shell with sudo -i and run the installer from there. If not, install Docker Engine 24.0 or later (on a NAS, the vendor's container package), then run the installer again" 2
sum_of() { awk -v f="$1" '$2 == f || $2 == "*" f { print $1 }' "$SUMS"; }
check() {
  want=$(sum_of "$(basename "$1")"); [ -n "$want" ] || die "the file $(basename "$1") is not listed in SHA256SUMS, so the installer cannot confirm it is genuine and did not use it. Make sure the file and SHA256SUMS come from the same release, then run the installer again"
  got=$(sha256sum "$1" | awk '{print $1}'); [ "$got" = "$want" ] || die "the file $(basename "$1") does not match its entry in SHA256SUMS, so it may be damaged, incomplete or from another release. It was not used. Download it again from the same release page and run the installer again"
}

if [ -n "$TAR" ]; then
  check "$TAR"
  IMAGE=$("$DOCKER" load -q -i "$TAR" | sed -n 's/^Loaded image ID: //p; s/^Loaded image: //p' | tail -n 1)
  IMAGE=$("$DOCKER" image inspect --format '{{.Id}}' "$IMAGE")
else
  digest=$(sum_of "image:ghcr.io/lisahq/ingat:$VERSION")
  [ -n "$digest" ] || die "SHA256SUMS has no entry for version $VERSION. Check that the version you typed matches the release this SHA256SUMS file came from, then run the installer again"
  IMAGE=ghcr.io/lisahq/ingat@sha256:$digest
  "$DOCKER" pull -q "$IMAGE" >/dev/null
fi

for d in "$ROOT" "$BACKUPS"; do
  [ -L "$d" ] && die "$d is a link that points to another folder (a symlink). Ingat needs a real folder here so that its files and backups cannot be redirected elsewhere. The ingat command was not installed. Choose a real folder with --root or --backups, or replace the link itself (not the folder it points to) with a real folder, then run the installer again"
  [ -d "$d" ] || { mkdir -p "$d"; chown 0:0 "$d"; chmod 0700 "$d"; }
done
[ "$(stat -c '%u:%g %a' "$ROOT")" = "0:0 700" ] || die "the folder $ROOT must belong to the root user and be readable by root only (owner root:root, mode 0700), so that nobody else can read the keys and state Ingat keeps there. The ingat command was not installed. To fix it run: chown 0:0 $ROOT && chmod 0700 $ROOT, then run the installer again. On a NAS, do not use a shared folder here: pick a plain folder with --root instead"
mkdir -p "$ROOT/bin"; chmod 0700 "$ROOT/bin"
"$DOCKER" volume inspect ingat-probe >/dev/null 2>&1 \
  || "$DOCKER" volume create --label io.github.lisahq.ingat.role=probe ingat-probe >/dev/null

run_image() { "$DOCKER" run --rm --pull never --log-driver none "$@"; }
# With the wrapper's own flags, so an engine the wrapper cannot run on (no docker-init) fails here, not later.
run_image --init --network host "$IMAGE" selftest --offline || die "the new version failed its first check (selftest --offline) on this Docker engine, so the ingat command was not installed or changed. The lines above say which check failed; keep them if you ask for help"

write_wrapper() {
  cat > "$1" <<EOF
#!/bin/sh
# $ROOT/bin/ingat — created by install.sh. Do not edit this file by hand: the next upgrade (install.sh with a newer version) replaces it and any edits would be lost.
set -eu
INGAT_VERSION='$VERSION'
INGAT_IMAGE='$IMAGE'
INGAT_ROOT='$ROOT'
INGAT_BACKUPS='$BACKUPS'
DOCKER='$DOCKER'
EOF
  cat >> "$1" <<'EOF'
PATH=/usr/bin:/bin; export PATH
[ "$(id -u)" -eq 0 ] || { echo "ingat: run as root: this command must be run by the root user (the top-level account of this machine), not by your normal user or a NAS admin user. Type sudo -i, press Enter, then run the same command again" >&2; exit 2; }
TTY=; if [ -t 0 ] && [ -t 1 ]; then TTY=-t; fi
FACTS=; for f in /etc.defaults/VERSION /etc/os-release; do [ -r "$f" ] && FACTS="$FACTS -v $f:/run/host$f:ro"; done
HOST_NAME=$(hostname); OPERATOR=${SUDO_USER:-root}
# shellcheck disable=SC2086
exec env -i PATH="$PATH" TERM="${TERM:-dumb}" "$DOCKER" run --rm -i $TTY --init --pull never --network host \
  --label io.github.lisahq.ingat.role=cli --log-driver none \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$INGAT_ROOT:$INGAT_ROOT" -v "$INGAT_BACKUPS:$INGAT_BACKUPS" \
  -v ingat-probe:/run/ingat/docker-root:ro $FACTS \
  -e TERM -e INGAT_ROOT="$INGAT_ROOT" -e INGAT_BACKUPS="$INGAT_BACKUPS" -e INGAT_IMAGE="$INGAT_IMAGE" \
  -e INGAT_WRAPPER_VERSION="$INGAT_VERSION" -e INGAT_HOST="$HOST_NAME" -e INGAT_OPERATOR="$OPERATOR" \
  "$INGAT_IMAGE" "$@"
EOF
  chmod 0700 "$1"
}
# fsync exactly the published file and its directory (never a global sync).
fsync() { run_image --entrypoint python3 -v "$ROOT/bin:$ROOT/bin" "$IMAGE" -I -c \
  'import os, sys
for p in sys.argv[1:]:
    fd = os.open(p, os.O_RDONLY)
    os.fsync(fd)
    os.close(fd)' "$@"; }

UPGRADE=
if [ -e "$ROOT/bin/ingat" ]; then
  UPGRADE=1
  for op in "$ROOT"/instances/*/ops/*/; do
    [ -d "$op" ] && [ ! -e "$op/result.json" ] && die "an operation is open ($op): Ingat is still in the middle of a job on one of your apps, so the upgrade stopped here and your current version and your apps were not changed. Finish that job first: run ingat status <name> (the name is the folder after instances/ in the path above) and it tells you how, usually ingat resume <name>. Then run this installer again" 2
  done
  write_wrapper "$ROOT/bin/ingat.new"
  "$ROOT/bin/ingat.new" selftest --host || { rm -f "$ROOT/bin/ingat.new"; die "selftest --host failed; kept the current version. The new version did not pass its own check on this machine, so your current version stays in place and your apps and backups were not touched. The lines above say which check failed; keep them if you ask for help" 3; }
  cp -p "$ROOT/bin/ingat" "$ROOT/bin/ingat.prev"
  fsync "$ROOT/bin/ingat.prev"
else
  write_wrapper "$ROOT/bin/ingat.new"
fi
fsync "$ROOT/bin/ingat.new"
mv -f "$ROOT/bin/ingat.new" "$ROOT/bin/ingat"
fsync "$ROOT/bin"
[ -z "$LINK" ] || ln -sfn "$ROOT/bin/ingat" "$LINK"
echo "installed version $VERSION ($IMAGE) at $ROOT/bin/ingat"
if [ -n "$UPGRADE" ]; then
  echo "Upgrade done: the new version already passed its check on this machine. The previous version is kept at $ROOT/bin/ingat.prev; run that file instead of ingat if the new version gives you trouble."
else
  echo "Next, once on this machine: run 'ingat host init' (it asks you to type this machine's name, as the hostname command prints it, to confirm), then 'ingat selftest --host' to check that Ingat works here (this takes a few minutes). The full first-time steps are in the operator guide: https://github.com/LisaHQ/ingat/blob/v$VERSION/docs/guide/operator-guide.md"
fi
