"""Hash-checked tool files: the primitives shared by scripts/toolchain.py (build time) and
atelier.tool_updates (the in-app updater). Nothing here trusts a download it has not hashed."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile

UA = {"User-Agent": "Atelier-toolchain"}


class ToolFileError(RuntimeError):
    pass


def sha256_file(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def download(url, sha256, store, timeout=300):
    """The file at `url` inside `store`, reused when its hash matches. A mismatch is never kept."""
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    if sha256:
        cached = store / sha256
        if cached.exists() and sha256_file(cached) == sha256:
            return cached
    request = urllib.request.Request(url, headers={**UA, "Accept": "application/octet-stream"})
    fd, tmp = tempfile.mkstemp(dir=store, prefix=".download-")
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(request, timeout=timeout) as response:
            shutil.copyfileobj(response, out)
        actual = sha256_file(tmp)
        if sha256 and actual != sha256:
            raise ToolFileError(f"Hash mismatch for {url}: expected {sha256}, got {actual}")
        final = store / actual
        os.replace(tmp, final)
        return final
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_member(archive, url, member):
    """One file's bytes out of a .zip / .tar.* release archive."""
    name = url.rsplit("/", 1)[-1].lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            return zf.read(member)
    if name.endswith((".tar.xz", ".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive) as tf:
            handle = tf.extractfile(member)
            if handle is None:
                raise ToolFileError(f"{member} is not a file in {name}")
            return handle.read()
    raise ToolFileError(f"Cannot extract from {name}")


def safe_relative(relative):
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ToolFileError(f"Unsafe tool path {relative!r}")
    return rel


def place(data, dest, relative, executable=False):
    """Write `data` to dest/relative atomically (temp file + replace)."""
    target = Path(dest).joinpath(*safe_relative(relative).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(data)
    if executable:
        tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, target)
    return target


def asset_files(asset):
    """[(relative path, sha256, executable)] an asset installs, from a lock/channel asset entry."""
    if "extract" in asset:
        return [(spec["to"], spec["sha256"], spec.get("executable", False)) for spec in asset["extract"].values()]
    targets = asset["to"] if isinstance(asset["to"], list) else [asset["to"]]
    return [(t, asset["sha256"], asset.get("executable", False)) for t in targets]


def materialize(asset, archive):
    """{relative path: bytes} for an asset, every member checked against its pinned hash."""
    out = {}
    if "extract" in asset:
        for member, spec in asset["extract"].items():
            data = read_member(archive, asset["url"], member)
            if sha256_bytes(data) != spec["sha256"]:
                raise ToolFileError(f"{member} does not match its pinned hash")
            out[spec["to"]] = data
    else:
        data = Path(archive).read_bytes()
        for target, _sha, _x in asset_files(asset):
            out[target] = data
    return out
