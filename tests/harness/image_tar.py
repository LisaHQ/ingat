"""The pipeline's tested image as per-architecture tarballs, and the release check against it (ADR-0029).

The build job runs one multi-arch buildx build with an OCI-layout output; its index digest names the tested image.

docker-tar writes the `docker load` tarball of one architecture by re-packaging that build's own blobs: the config and
layers of the architecture's manifest, each checked against its SHA-256 digest. It is not a second build, so a lane
loads exactly the layers and the configuration that the tested index references.

check-release checks a `docker save` tarball of the release image against the tested image of its architecture: the
same layers (diff IDs) and runtime configuration, plus one final layer that holds only tested.json, and every layer
file in the tarball hashes to its diff ID.

usage: image_tar.py docker-tar LAYOUT_DIR INDEX_DIGEST ARCH OUT_TAR NAME
       image_tar.py check-release LAYOUT_DIR INDEX_DIGEST ARCH RELEASE_TAR TESTED_JSON
"""

import argparse
import gzip
import hashlib
import io
import json
import pathlib
import tarfile
from collections.abc import Callable
from typing import IO, Any

PACKAGE_TESTED_JSON = "usr/local/lib/python3.13/site-packages/ingat/tested.json"


class ImageError(Exception):
    pass


def verified(layout: pathlib.Path, digest: str) -> pathlib.Path:
    """The blob file of a digest in an OCI layout, after checking that its content has that digest."""
    alg, _, hex_ = digest.partition(":")
    if alg != "sha256" or len(hex_) != 64 or not all(c in "0123456789abcdef" for c in hex_):
        raise ImageError(f"not a sha256 digest: {digest!r}")
    path = layout / "blobs" / alg / hex_
    with path.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != hex_:
            raise ImageError(f"blob {digest} does not match its digest")
    return path


def platform_manifest(layout: pathlib.Path, index_digest: str, arch: str) -> tuple[str, dict[str, Any]]:
    """The digest and content of the one linux/<arch> image manifest of the index (attestations are skipped)."""
    index = json.loads(verified(layout, index_digest).read_bytes())
    found = [
        d["digest"]
        for d in index.get("manifests", [])
        if d.get("platform", {}).get("os") == "linux" and d["platform"].get("architecture") == arch
    ]
    if len(found) != 1:
        raise ImageError(f"index {index_digest} has {len(found)} linux/{arch} manifests, expected 1")
    return found[0], json.loads(verified(layout, found[0]).read_bytes())


def docker_tar(layout: pathlib.Path, index_digest: str, arch: str, out_path: pathlib.Path, name: str) -> None:
    manifest_digest, manifest = platform_manifest(layout, index_digest, arch)
    config = manifest["config"]["digest"]
    layers = [layer["digest"] for layer in manifest["layers"]]
    member = {d: "blobs/sha256/" + d.removeprefix("sha256:") for d in [config, *layers]}
    entry = {"Config": member[config], "RepoTags": [name], "Layers": [member[d] for d in layers]}
    # Fixed member metadata (mtime 0, root, 0644) makes the tarball a function of the blobs alone.
    try:
        with tarfile.open(out_path, "w", format=tarfile.PAX_FORMAT) as out:
            for digest in dict.fromkeys([config, *layers]):
                path = verified(layout, digest)
                info = tarfile.TarInfo(member[digest])
                info.size, info.mode = path.stat().st_size, 0o644
                with path.open("rb") as f:
                    out.addfile(info, f)
            data = json.dumps([entry]).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size, info.mode = len(data), 0o644
            out.addfile(info, io.BytesIO(data))
    except BaseException:
        out_path.unlink(missing_ok=True)
        raise
    print(f"{out_path.name}: linux/{arch} manifest {manifest_digest} config {config} of index {index_digest}")


def diff_id(f: IO[bytes]) -> str:
    """The diff ID of a layer file: the SHA-256 of its uncompressed tar (docker save writes it plain or gzipped)."""
    gzipped = f.read(2) == b"\x1f\x8b"
    f.seek(0)
    read: Callable[[int], bytes] = gzip.GzipFile(fileobj=f).read if gzipped else f.read
    h = hashlib.sha256()
    while chunk := read(1 << 20):
        h.update(chunk)
    return "sha256:" + h.hexdigest()


def check_release(layout: pathlib.Path, index_digest: str, arch: str, release: pathlib.Path, tested: bytes) -> None:
    _, manifest = platform_manifest(layout, index_digest, arch)
    base = json.loads(verified(layout, manifest["config"]["digest"]).read_bytes())
    files: dict[str, bytes | None] = {}
    with tarfile.open(release) as tar:

        def member(name: str) -> IO[bytes]:
            f = tar.extractfile(name)
            if f is None:
                raise ImageError(f"{release.name}: {name} is not a file")
            return f

        entries = json.loads(member("manifest.json").read())
        if len(entries) != 1:
            raise ImageError(f"{release.name}: holds {len(entries)} images, expected 1")
        config = json.loads(member(entries[0]["Config"]).read())
        diff_ids, base_ids = config["rootfs"]["diff_ids"], base["rootfs"]["diff_ids"]
        if (config.get("os"), config.get("architecture")) != ("linux", arch):
            raise ImageError(f"{release.name}: not a linux/{arch} image")
        if len(diff_ids) != len(base_ids) + 1 or diff_ids[:-1] != base_ids:
            raise ImageError(f"{release.name}: its layers are not the tested layers plus one")
        if config.get("config") != base.get("config"):
            raise ImageError(f"{release.name}: its runtime configuration differs from the tested image")
        # Every layer file of the published tarball, not only the configuration, must be the layer its diff ID names.
        layers = entries[0]["Layers"]
        if [diff_id(member(name)) for name in layers] != diff_ids:
            raise ImageError(f"{release.name}: its layer files do not match the diff IDs of its configuration")
        with tarfile.open(fileobj=member(layers[-1])) as layer:
            for m in layer.getmembers():
                if not m.isdir():
                    f = layer.extractfile(m) if m.isreg() else None
                    files[m.name.removeprefix("./")] = f.read() if f else None
    if list(files) != [PACKAGE_TESTED_JSON]:
        raise ImageError(f"{release.name}: the final layer holds {sorted(files)}, expected only {PACKAGE_TESTED_JSON}")
    if files[PACKAGE_TESTED_JSON] != tested:
        raise ImageError(f"{release.name}: the final layer holds another tested.json than the one given")
    print(f"{release.name}: the tested linux/{arch} image of {index_digest} plus one layer holding tested.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    tar = sub.add_parser("docker-tar")
    check = sub.add_parser("check-release")
    for p in (tar, check):
        p.add_argument("layout", type=pathlib.Path)
        p.add_argument("index_digest")
        p.add_argument("arch")
    tar.add_argument("out_tar", type=pathlib.Path)
    tar.add_argument("name")
    check.add_argument("release_tar", type=pathlib.Path)
    check.add_argument("tested_json", type=pathlib.Path)
    a = parser.parse_args()
    try:
        if a.command == "docker-tar":
            docker_tar(a.layout, a.index_digest, a.arch, a.out_tar, a.name)
        else:
            check_release(a.layout, a.index_digest, a.arch, a.release_tar, a.tested_json.read_bytes())
    except (ImageError, OSError, KeyError, ValueError) as e:
        raise SystemExit(f"image_tar: {e}") from e


if __name__ == "__main__":
    main()
