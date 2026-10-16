#!/bin/sh
# Build the tool image from the pins in image/versions.lock.
# usage: sh image/build.sh <tag> [extra docker build/buildx arguments...]
# Single-architecture builds use `docker build`; the CI build job passes BUILD_CMD="buildx build" with
# `--platform linux/amd64,linux/arm64` and an OCI-layout output: the one multi-arch build of the pipeline (ADR-0029).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tag=${1:?usage: build.sh <tag> [args...]}
shift
args=
while IFS='=' read -r key value; do
  case "$key" in ''|'#'*) continue ;; DIND_*) continue ;; esac
  args="$args --build-arg $key=$value"
done < "$here/versions.lock"
version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$here/../src/ingat/__init__.py")
revision=$(git -C "$here/.." rev-parse HEAD 2>/dev/null || echo unknown)
# shellcheck disable=SC2086
exec docker ${BUILD_CMD:-build} $args --build-arg VERSION="$version" --build-arg REVISION="$revision" \
  -f "$here/Dockerfile" -t "$tag" "$@" "$here/.."
