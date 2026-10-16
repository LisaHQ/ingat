#!/bin/sh
# Install or upgrade the tool on one host (ARCHITECTURE.md §3.4, §3.5). Run as root next to the release's SHA256SUMS:
#   sh install.sh --version 0.1.0 [--root /srv/ingat] [--backups /srv/ingat-backups] [--from-tar FILE] [--link PATH]
# A platform profile passes its own roots (the DSM profile: --root /volume1/ingat --backups /volume1/ingat-backups).
set -eu
die() { echo "install: $*" >&2; exit "${2:-1}"; }
[ "$(id -u)" -eq 0 ] || die "run as root (sudo -i)" 2
VERSION= ROOT=/srv/ingat BACKUPS=/srv/ingat-backups TAR= LINK=
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION=${2:?}; shift 2 ;;
    --root) ROOT=${2:?}; shift 2 ;;
    --backups) BACKUPS=${2:?}; shift 2 ;;
    --from-tar) TAR=${2:?}; shift 2 ;;
    --link) LINK=${2:?}; shift 2 ;;
    *) die "unknown argument $1" 2 ;;
  esac
done
[ -n "$VERSION" ] || die "--version is required" 2
case "$ROOT$BACKUPS" in *[!A-Za-z0-9/._-]*) die "roots may contain only [A-Za-z0-9/._-]" 2 ;; esac
case "$ROOT" in /*) ;; *) die "--root must be absolute" 2 ;; esac
case "$BACKUPS" in /*) ;; *) die "--backups must be absolute" 2 ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
SUMS=$HERE/SHA256SUMS
[ -r "$SUMS" ] || die "SHA256SUMS not found next to install.sh"
DOCKER=$(command -v docker) || die "docker not found in PATH" 2
sum_of() { awk -v f="$1" '$2 == f || $2 == "*" f { print $1 }' "$SUMS"; }
check() {
  want=$(sum_of "$(basename "$1")"); [ -n "$want" ] || die "$(basename "$1") is not listed in SHA256SUMS"
  got=$(sha256sum "$1" | awk '{print $1}'); [ "$got" = "$want" ] || die "checksum mismatch for $(basename "$1")"
}

if [ -n "$TAR" ]; then
  check "$TAR"
  IMAGE=$("$DOCKER" load -q -i "$TAR" | sed -n 's/^Loaded image ID: //p; s/^Loaded image: //p' | tail -n 1)
  IMAGE=$("$DOCKER" image inspect --format '{{.Id}}' "$IMAGE")
else
  digest=$(sum_of "image:ghcr.io/lisahq/ingat:$VERSION")
  [ -n "$digest" ] || die "SHA256SUMS lists no image for version $VERSION"
  IMAGE=ghcr.io/lisahq/ingat@sha256:$digest
  "$DOCKER" pull -q "$IMAGE" >/dev/null
fi

for d in "$ROOT" "$BACKUPS"; do
  [ -L "$d" ] && die "$d is a symlink"
  [ -d "$d" ] || { mkdir -p "$d"; chown 0:0 "$d"; chmod 0700 "$d"; }
done
[ "$(stat -c '%u:%g %a' "$ROOT")" = "0:0 700" ] || die "$ROOT must be root:root 0700"
mkdir -p "$ROOT/bin"; chmod 0700 "$ROOT/bin"
"$DOCKER" volume inspect ingat-probe >/dev/null 2>&1 \
  || "$DOCKER" volume create --label io.github.lisahq.ingat.role=probe ingat-probe >/dev/null

run_image() { "$DOCKER" run --rm --pull never --log-driver none "$@"; }
run_image "$IMAGE" selftest --offline || die "selftest --offline failed with the new image"

write_wrapper() {
  cat > "$1" <<EOF
#!/bin/sh
# $ROOT/bin/ingat — written by install.sh; replaced atomically by an upgrade; never edited by hand.
set -eu
INGAT_VERSION='$VERSION'
INGAT_IMAGE='$IMAGE'
INGAT_ROOT='$ROOT'
INGAT_BACKUPS='$BACKUPS'
DOCKER='$DOCKER'
EOF
  cat >> "$1" <<'EOF'
PATH=/usr/bin:/bin; export PATH
[ "$(id -u)" -eq 0 ] || { echo "ingat: run as root (sudo -i)" >&2; exit 2; }
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

if [ -e "$ROOT/bin/ingat" ]; then
  for op in "$ROOT"/instances/*/ops/*/; do
    [ -d "$op" ] && [ ! -e "$op/result.json" ] && die "an operation is open ($op); finish it before upgrading" 2
  done
  write_wrapper "$ROOT/bin/ingat.new"
  "$ROOT/bin/ingat.new" selftest --host || { rm -f "$ROOT/bin/ingat.new"; die "selftest --host failed; kept the current version" 3; }
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
