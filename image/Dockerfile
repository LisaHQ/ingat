# The tool image (ARCHITECTURE.md §3.2): Python 3.13, the static docker CLI, the Compose plugin, git, the
# package and the fx-lite / fx-web fixtures. Build with image/build.sh, which passes the pins of image/versions.lock.
ARG PYTHON_BASE
FROM ${PYTHON_BASE}

ARG DOCKER_CLI_VERSION
ARG DOCKER_CLI_SHA256_AMD64
ARG DOCKER_CLI_SHA256_ARM64
ARG COMPOSE_VERSION
ARG COMPOSE_SHA256_AMD64
ARG COMPOSE_SHA256_ARM64
ARG VERSION=0.0.0
ARG REVISION=unknown

RUN set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends git openssh-client tar ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    case "$(dpkg --print-architecture)" in \
      amd64) a=x86_64; c="$DOCKER_CLI_SHA256_AMD64"; k="$COMPOSE_SHA256_AMD64";; \
      arm64) a=aarch64; c="$DOCKER_CLI_SHA256_ARM64"; k="$COMPOSE_SHA256_ARM64";; \
      *) echo "unsupported architecture" >&2; exit 1;; \
    esac; \
    fetch() { python3 -I -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$1" "$2"; }; \
    fetch "https://download.docker.com/linux/static/stable/$a/docker-$DOCKER_CLI_VERSION.tgz" /tmp/docker.tgz; \
    echo "$c  /tmp/docker.tgz" | sha256sum -c -; \
    tar -xzf /tmp/docker.tgz -C /tmp docker/docker; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    fetch "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-$a" /tmp/compose; \
    echo "$k  /tmp/compose" | sha256sum -c -; \
    install -D -m 0755 /tmp/compose /usr/local/lib/docker/cli-plugins/docker-compose; \
    rm -rf /tmp/docker /tmp/docker.tgz /tmp/compose; \
    docker --version; docker compose version

COPY src/ingat /usr/local/lib/python3.13/site-packages/ingat
COPY fixtures /opt/fixtures
RUN install -m 0755 /opt/fixtures/fx-lite/fx-lite /usr/local/bin/fx-lite \
    && python3 -I -m compileall -q /usr/local/lib/python3.13/site-packages/ingat

LABEL org.opencontainers.image.source="https://github.com/LisaHQ/ingat" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
ENTRYPOINT ["python3", "-I", "-m", "ingat"]
