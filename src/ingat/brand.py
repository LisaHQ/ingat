"""Product identity: the only module that may spell the product's names, labels and roots (ADR-0003)."""

PRODUCT = "Ingat"
CLI = "ingat"
REPOSITORY = "github.com/LisaHQ/ingat"
IMAGE_REPO = "ghcr.io/lisahq/ingat"
LABEL_NS = "io.github.lisahq.ingat."
ENV_PREFIX = "INGAT_"
DEFAULT_ROOT = "/srv/ingat"
DEFAULT_BACKUPS = "/srv/ingat-backups"
PROBE_VOLUME = "ingat-probe"
PROBE_MOUNT = "/run/ingat/docker-root"
HOST_FACTS_DIR = "/run/host"
MANIFEST_FILE = "ingat.toml"
EXECUTOR_PREFIX = "ingat-exec-"
SELFTEST_PREFIX = "ingat-selftest-"


def label(key: str) -> str:
    return LABEL_NS + key


def env(name: str) -> str:
    return ENV_PREFIX + name


def executor_name(instance: str | None) -> str:
    """Executor container name; `None` is the host-scope executor."""
    return EXECUTOR_PREFIX + (instance if instance is not None else "-host")
